import json

from aws_cdk import Aws, CustomResource, Duration, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
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

        index_creator = lambda_.Function(
            self,
            "VectorIndexCreator",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            timeout=Duration.minutes(5),
            code=lambda_.Code.from_inline(INDEX_CREATOR_CODE),
        )
        index_creator.add_to_role_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=["*"])
        )

        access_policy = aoss.CfnAccessPolicy(
            self,
            "VectorAccessPolicy",
            name=f"{app_name}-vector-access",
            type="data",
            policy=json.dumps(
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
                        "Principal": [self.kb_role.role_arn, index_creator.role.role_arn],
                    }
                ]
            ),
        )
        self.collection.add_dependency(access_policy)
        self.kb_role.add_to_policy(
            iam.PolicyStatement(actions=["aoss:APIAccessAll"], resources=[self.collection.attr_arn])
        )

        index_resource = CustomResource(
            self,
            "VectorIndex",
            service_token=index_creator.function_arn,
            properties={
                "Endpoint": self.collection.attr_collection_endpoint,
                "IndexName": vector_index_name,
                "VectorField": "bedrock-knowledge-base-default-vector",
                "TextField": "AMAZON_BEDROCK_TEXT_CHUNK",
                "MetadataField": "AMAZON_BEDROCK_METADATA",
                "Dimensions": 1024,
            },
        )
        index_resource.node.add_dependency(self.collection)
        index_resource.node.add_dependency(access_policy)
        # Ensure Lambda IAM policy is ready before invoking
        if index_creator.role and index_creator.role.node.try_find_child("DefaultPolicy"):
            index_resource.node.add_dependency(index_creator.role.node.find_child("DefaultPolicy"))

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
        self.knowledge_base.node.add_dependency(index_resource)

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


INDEX_CREATOR_CODE = r'''
import json
import time
import urllib.request

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

session = boto3.Session()
region = session.region_name or "us-east-1"


def handler(event, _context):
    props = event["ResourceProperties"]
    endpoint = props["Endpoint"].rstrip("/")
    index_name = props["IndexName"]
    physical_id = f"{endpoint}/{index_name}"

    try:
        if event["RequestType"] in {"Create", "Update"}:
            create_index(endpoint, index_name, props)
        elif event["RequestType"] == "Delete":
            delete_index(endpoint, index_name)
        send(event, "SUCCESS", {"PhysicalResourceId": physical_id})
    except Exception as exc:
        send(event, "FAILED", {"Reason": str(exc), "PhysicalResourceId": physical_id})


def create_index(endpoint, index_name, props):
    mapping = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                props["VectorField"]: {
                    "type": "knn_vector",
                    "dimension": int(props["Dimensions"]),
                    "method": {"name": "hnsw", "engine": "faiss", "space_type": "cosinesimil"},
                },
                props["TextField"]: {"type": "text"},
                props["MetadataField"]: {"type": "object", "enabled": True},
            }
        },
    }
    # AOSS data access policy propagation can take up to 3–5 minutes
    time.sleep(60)
    for attempt in range(24):
        result = request("PUT", f"{endpoint}/{index_name}", mapping, ignore_statuses={200, 201, 400, 403})
        if result["status"] != 403:
            break
        time.sleep(10)
    else:
        raise PermissionError(f"Still getting 403 after retries creating index {index_name}")
    for _ in range(30):
        result = request("GET", f"{endpoint}/{index_name}", None, ignore_statuses={200, 404})
        if result["status"] == 200:
            return
        time.sleep(5)
    raise TimeoutError(f"index {index_name} was not visible after creation")


def delete_index(endpoint, index_name):
    request("DELETE", f"{endpoint}/{index_name}", None, ignore_statuses={200, 202, 404})


def request(method, url, payload, ignore_statuses):
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    creds = session.get_credentials().get_frozen_credentials()
    aws_request = AWSRequest(method=method, url=url, data=body, headers={"Content-Type": "application/json"})
    SigV4Auth(creds, "aoss", region).add_auth(aws_request)
    http_request = urllib.request.Request(url, data=body or None, headers=dict(aws_request.headers), method=method)
    try:
        with urllib.request.urlopen(http_request, timeout=30) as response:
            return {"status": response.status, "body": response.read().decode("utf-8")}
    except urllib.error.HTTPError as exc:
        if exc.code in ignore_statuses:
            return {"status": exc.code, "body": exc.read().decode("utf-8")}
        raise


def send(event, status, data):
    body = json.dumps(
        {
            "Status": status,
            "Reason": data.get("Reason", "See CloudWatch Logs"),
            "PhysicalResourceId": data.get("PhysicalResourceId", event.get("PhysicalResourceId", "vector-index")),
            "StackId": event["StackId"],
            "RequestId": event["RequestId"],
            "LogicalResourceId": event["LogicalResourceId"],
            "Data": data,
        }
    ).encode("utf-8")
    request = urllib.request.Request(event["ResponseURL"], data=body, method="PUT", headers={"content-type": "", "content-length": str(len(body))})
    urllib.request.urlopen(request, timeout=30).read()
'''
