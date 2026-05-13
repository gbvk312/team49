from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct


class StorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, app_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.key = kms.Key(
            self,
            "CorpusKey",
            alias=f"alias/{app_name}-corpus",
            enable_key_rotation=True,
        )

        bucket_defaults = dict(
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.key,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            versioned=True,
            event_bridge_enabled=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        self.raw_bucket = s3.Bucket(
            self,
            "RawCorpusBucket",
            bucket_name=None,
            **bucket_defaults,
        )
        self.chunks_bucket = s3.Bucket(
            self,
            "ChunksBucket",
            bucket_name=None,
            lifecycle_rules=[
                s3.LifecycleRule(
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                    noncurrent_version_expiration=Duration.days(30),
                )
            ],
            **bucket_defaults,
        )

        self.chunks_table = dynamodb.Table(
            self,
            "ChunksTable",
            partition_key=dynamodb.Attribute(name="chunk_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.chunks_table.add_global_secondary_index(
            index_name="by_spec_release",
            partition_key=dynamodb.Attribute(name="spec_release", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="section", type=dynamodb.AttributeType.STRING),
        )
        self.chunks_table.add_global_secondary_index(
            index_name="by_source_type",
            partition_key=dynamodb.Attribute(name="source_type", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="feature", type=dynamodb.AttributeType.STRING),
        )

        self.features_table = dynamodb.Table(
            self,
            "FeaturesTable",
            partition_key=dynamodb.Attribute(name="feature_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(point_in_time_recovery_enabled=True),
            removal_policy=RemovalPolicy.RETAIN,
        )
        self.features_table.add_global_secondary_index(
            index_name="by_spec_section",
            partition_key=dynamodb.Attribute(name="spec", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="section", type=dynamodb.AttributeType.STRING),
        )
        self.features_table.add_global_secondary_index(
            index_name="by_feature_name",
            partition_key=dynamodb.Attribute(name="feature", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="spec", type=dynamodb.AttributeType.STRING),
        )

        CfnOutput(self, "RawBucketName", value=self.raw_bucket.bucket_name)
        CfnOutput(self, "ChunksBucketName", value=self.chunks_bucket.bucket_name)
