import json

from aws_cdk import Aws, CfnOutput, Fn, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_opensearchserverless as aoss
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
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        collection_name = f"{app_name}-vectors"
        vector_index_name = "bedrock-knowledge-base-default-index"

        self.kb_role = iam.Role(
            self,
            "KnowledgeBaseRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": Aws.ACCOUNT_ID},
                    "ArnLike": {"aws:SourceArn": f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:knowledge-base/*"},
                },
            ),
        )
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}::foundation-model/{embedding_model}"],
            )
        )
        chunks_bucket.grant_read(self.kb_role)

        encryption_policy = aoss.CfnSecurityPolicy(
            self,
            "VectorEncryptionPolicy",
            name=f"{app_name}-vector-encryption",
            type="encryption",
            policy=json.dumps(
                {
                    "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{collection_name}"]}],
                    "AWSOwnedKey": True,
                }
            ),
        )
        network_policy = aoss.CfnSecurityPolicy(
            self,
            "VectorNetworkPolicy",
            name=f"{app_name}-vector-network",
            type="network",
            policy=json.dumps(
                [
                    {
                        "Rules": [
                            {"ResourceType": "collection", "Resource": [f"collection/{collection_name}"]},
                            {"ResourceType": "dashboard", "Resource": [f"collection/{collection_name}"]},
                        ],
                        "AllowFromPublic": True,
                    }
                ]
            ),
        )

        self.collection = aoss.CfnCollection(
            self,
            "VectorCollection",
            name=collection_name,
            type="VECTORSEARCH",
        )
        self.collection.add_dependency(encryption_policy)
        self.collection.add_dependency(network_policy)

        # Use Fn.sub to resolve role ARNs at deploy time
        # Include the deployer's role so post-deploy script can create the index
        access_policy = aoss.CfnAccessPolicy(
            self,
            "VectorAccessPolicy",
            name=f"{app_name}-vector-access",
            type="data",
            policy=Fn.sub(
                json.dumps(
                    [
                        {
                            "Rules": [
                                {
                                    "ResourceType": "collection",
                                    "Resource": [f"collection/{collection_name}"],
                                    "Permission": ["aoss:CreateCollectionItems", "aoss:DescribeCollectionItems", "aoss:UpdateCollectionItems"],
                                },
                                {
                                    "ResourceType": "index",
                                    "Resource": [f"index/{collection_name}/*"],
                                    "Permission": [
                                        "aoss:CreateIndex",
                                        "aoss:DescribeIndex",
                                        "aoss:ReadDocument",
                                        "aoss:WriteDocument",
                                        "aoss:UpdateIndex",
                                    ],
                                },
                            ],
                            "Principal": ["${KbRoleArn}", "arn:aws:iam::715001841576:role/vscode-server-CodeEditorInstanceBootstrapRole-81AXesWau8rB"],
                        }
                    ]
                ),
                {
                    "KbRoleArn": self.kb_role.role_arn,
                },
            ),
        )
        self.collection.add_dependency(access_policy)
        self.kb_role.add_to_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=[self.collection.attr_arn])
        )

        # Output collection endpoint for post-deploy index creation script
        CfnOutput(self, "CollectionEndpoint", value=self.collection.attr_collection_endpoint)
        CfnOutput(self, "VectorIndexName", value=vector_index_name)

        # The KnowledgeBase requires the vector index to exist.
        # The index is created by the deploy script between CDK deploy phases.
        # On first deploy, set SKIP_KB=1 env var to deploy collection first.
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name=f"{app_name}-knowledge-base",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}::foundation-model/{embedding_model}"
                },
            },
            storage_configuration={
                "type": "OPENSEARCH_SERVERLESS",
                "opensearchServerlessConfiguration": {
                    "collectionArn": self.collection.attr_arn,
                    "vectorIndexName": vector_index_name,
                    "fieldMapping": {
                        "vectorField": "bedrock-knowledge-base-default-vector",
                        "textField": "AMAZON_BEDROCK_TEXT_CHUNK",
                        "metadataField": "AMAZON_BEDROCK_METADATA",
                    },
                },
            },
        )
        self.knowledge_base.node.add_dependency(self.collection)

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

