import json

from aws_cdk import Aws, CfnOutput, Fn, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_opensearchserverless as aoss
from aws_cdk import aws_s3 as s3
from constructs import Construct


class VectorStoreStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        chunks_bucket: s3.IBucket,
        embedding_model: str,
        deployer_role_arn: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        collection_name = f"{app_name}-vectors"

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
                            "Principal": ["${KbRoleArn}", "${DeployerRoleArn}"],
                        }
                    ]
                ),
                {
                    "KbRoleArn": self.kb_role.role_arn,
                    "DeployerRoleArn": deployer_role_arn,
                },
            ),
        )
        self.collection.add_dependency(access_policy)
        self.kb_role.add_to_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=[self.collection.attr_arn])
        )

        CfnOutput(self, "CollectionEndpoint", value=self.collection.attr_collection_endpoint)
        CfnOutput(self, "CollectionArn", value=self.collection.attr_arn)

        self.collection_arn = self.collection.attr_arn
        self.collection_endpoint = self.collection.attr_collection_endpoint
