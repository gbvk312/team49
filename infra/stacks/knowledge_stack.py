from aws_cdk import Aws, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


class KnowledgeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        chunks_bucket: s3.IBucket,
        embedding_model: str,
        collection_arn: str,
        kb_role: iam.IRole,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vector_index_name = "bedrock-knowledge-base-default-index"

        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name=f"{app_name}-knowledge-base",
            role_arn=kb_role.role_arn,
            knowledge_base_configuration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}::foundation-model/{embedding_model}"
                },
            },
            storage_configuration={
                "type": "OPENSEARCH_SERVERLESS",
                "opensearchServerlessConfiguration": {
                    "collectionArn": collection_arn,
                    "vectorIndexName": vector_index_name,
                    "fieldMapping": {
                        "vectorField": "bedrock-knowledge-base-default-vector",
                        "textField": "AMAZON_BEDROCK_TEXT_CHUNK",
                        "metadataField": "AMAZON_BEDROCK_METADATA",
                    },
                },
            },
        )

        self.data_source = bedrock.CfnDataSource(
            self,
            "ChunksDataSource",
            name=f"{app_name}-chunks",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            data_source_configuration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": chunks_bucket.bucket_arn,
                    "inclusionPrefixes": ["chunks/"],
                },
            },
            vector_ingestion_configuration={"chunkingConfiguration": {"chunkingStrategy": "NONE"}},
        )

        self.knowledge_base_id = self.knowledge_base.attr_knowledge_base_id
        self.data_source_id = self.data_source.attr_data_source_id
