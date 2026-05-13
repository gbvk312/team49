from pathlib import Path

from aws_cdk import Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from aws_cdk import aws_stepfunctions_tasks as tasks
from constructs import Construct


ROOT = Path(__file__).resolve().parents[2]


class PipelineStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        raw_bucket: s3.IBucket,
        chunks_bucket: s3.IBucket,
        chunks_table: dynamodb.ITable,
        features_table: dynamodb.ITable,
        knowledge_base_id: str,
        data_source_id: str,
        neptune_endpoint: str,
        neptune_security_group: ec2.ISecurityGroup,
        vpc: ec2.IVpc,
        foundation_model: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        image_textract = self.lambda_function(
            "ImageTextract",
            "image_textract",
            environment={"CHUNKS_BUCKET": chunks_bucket.bucket_name},
        )
        metadata_extractor = self.lambda_function(
            "MetadataExtractor",
            "metadata_extractor",
            environment={"FOUNDATION_MODEL": foundation_model},
        )
        semantic_chunker = self.lambda_function(
            "SemanticChunker",
            "semantic_chunker",
            environment={"CHUNKS_BUCKET": chunks_bucket.bucket_name},
        )
        metadata_writer = self.lambda_function(
            "MetadataWriter",
            "metadata_writer",
            environment={"CHUNKS_TABLE": chunks_table.table_name, "FEATURES_TABLE": features_table.table_name},
        )
        relationship_extractor = self.lambda_function(
            "RelationshipExtractor",
            "relationship_extractor",
            environment={"FOUNDATION_MODEL": foundation_model},
        )
        neptune_writer = self.lambda_function(
            "NeptuneWriter",
            "neptune_writer",
            environment={"NEPTUNE_ENDPOINT": neptune_endpoint},
            vpc=vpc,
            security_groups=[neptune_security_group],
            timeout=Duration.minutes(5),
        )
        kb_sync = self.lambda_function(
            "KnowledgeBaseSync",
            "kb_sync",
            environment={"KNOWLEDGE_BASE_ID": knowledge_base_id, "DATA_SOURCE_ID": data_source_id},
        )

        raw_bucket.grant_read(image_textract)
        chunks_bucket.grant_read_write(image_textract)
        chunks_bucket.grant_read(metadata_extractor)
        chunks_bucket.grant_read_write(metadata_extractor)
        chunks_bucket.grant_read_write(semantic_chunker)
        chunks_bucket.grant_read_write(relationship_extractor)
        chunks_table.grant_write_data(metadata_writer)
        features_table.grant_write_data(metadata_writer)

        image_textract.add_to_role_policy(iam.PolicyStatement(actions=["textract:AnalyzeDocument"], resources=["*"]))
        for fn in [metadata_extractor, relationship_extractor]:
            fn.add_to_role_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=["*"]))
        neptune_writer.add_to_role_policy(iam.PolicyStatement(actions=["neptune-db:connect"], resources=["*"]))
        kb_sync.add_to_role_policy(
            iam.PolicyStatement(actions=["bedrock:StartIngestionJob"], resources=["*"])
        )

        textract_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "ExtractImageText", lambda_function=image_textract, output_path="$.Payload"))
        metadata_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "ExtractMetadata", lambda_function=metadata_extractor, output_path="$.Payload"))
        chunk_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "SemanticChunk", lambda_function=semantic_chunker, output_path="$.Payload"))
        metadata_write_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "WriteMetadata", lambda_function=metadata_writer, output_path="$.Payload"))
        relationships_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "ExtractRelationships", lambda_function=relationship_extractor, output_path="$.Payload"))
        graph_write_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "WriteGraph", lambda_function=neptune_writer, output_path="$.Payload"))
        kb_sync_task = self.with_lambda_retry(tasks.LambdaInvoke(self, "StartKnowledgeBaseIngestion", lambda_function=kb_sync, output_path="$.Payload"))

        fanout = sfn.Parallel(self, "PersistKnowledgeArtifacts", result_path="$.parallel_results")
        fanout.branch(metadata_write_task)
        fanout.branch(relationships_task.next(graph_write_task))

        definition = textract_task.next(metadata_task).next(chunk_task).next(fanout).next(kb_sync_task)
        self.state_machine = sfn.StateMachine(
            self,
            "IngestionStateMachine",
            state_machine_name=f"{app_name}-ingestion",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            timeout=Duration.hours(2),
            state_machine_type=sfn.StateMachineType.STANDARD,
        )

        for prefix, rule_id in [("3GPP/marked/", "ThreeGppUploadRule"), ("whitepapers/", "WhitepaperUploadRule")]:
            events.Rule(
                self,
                rule_id,
                event_pattern=events.EventPattern(
                    source=["aws.s3"],
                    detail_type=["Object Created"],
                    detail={"bucket": {"name": [raw_bucket.bucket_name]}, "object": {"key": [{"prefix": prefix}]}},
                ),
                targets=[targets.SfnStateMachine(self.state_machine)],
            )

        self.functions = [
            image_textract,
            metadata_extractor,
            semantic_chunker,
            metadata_writer,
            relationship_extractor,
            neptune_writer,
            kb_sync,
        ]

    def lambda_function(
        self,
        construct_id: str,
        folder: str,
        *,
        environment: dict[str, str],
        vpc: ec2.IVpc | None = None,
        security_groups: list[ec2.ISecurityGroup] | None = None,
        timeout: Duration = Duration.minutes(2),
    ) -> lambda_.Function:
        return lambda_.Function(
            self,
            construct_id,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(ROOT / "lambdas" / folder)),
            timeout=timeout,
            memory_size=512,
            environment=environment,
            vpc=vpc,
            security_groups=security_groups,
        )

    def with_lambda_retry(self, task: tasks.LambdaInvoke) -> tasks.LambdaInvoke:
        return task.add_retry(
            errors=["Lambda.ServiceException", "Lambda.SdkClientException", "Lambda.TooManyRequestsException"],
            interval=Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2,
        )
