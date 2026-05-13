from pathlib import Path

from aws_cdk import Aws, Duration, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct


ROOT = Path(__file__).resolve().parents[2]


class AgentStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        chunks_table: dynamodb.ITable,
        features_table: dynamodb.ITable,
        knowledge_base_id: str,
        neptune_endpoint: str,
        neptune_security_group: ec2.ISecurityGroup,
        vpc: ec2.IVpc,
        foundation_model: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vector_search = self.tool_lambda(
            "VectorSearchTool",
            "vector_search",
            environment={"KNOWLEDGE_BASE_ID": knowledge_base_id},
        )
        whitepaper_lookup = self.tool_lambda(
            "WhitepaperLookupTool",
            "whitepaper_lookup",
            environment={"KNOWLEDGE_BASE_ID": knowledge_base_id},
        )
        metadata_query = self.tool_lambda(
            "MetadataQueryTool",
            "metadata_query",
            environment={"CHUNKS_TABLE": chunks_table.table_name, "FEATURES_TABLE": features_table.table_name},
        )
        graph_search = self.tool_lambda(
            "GraphSearchTool",
            "graph_search",
            environment={"NEPTUNE_ENDPOINT": neptune_endpoint},
            vpc=vpc,
            security_groups=[neptune_security_group],
        )
        chunks_table.grant_read_data(metadata_query)
        features_table.grant_read_data(metadata_query)
        for fn in [vector_search, whitepaper_lookup]:
            fn.add_to_role_policy(iam.PolicyStatement(actions=["bedrock:Retrieve"], resources=["*"]))
        graph_search.add_to_role_policy(iam.PolicyStatement(actions=["neptune-db:connect"], resources=["*"]))

        self.agent_role = iam.Role(
            self,
            "AgentRole",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
        )
        self.agent_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=["*"],
            )
        )
        self.agent_role.add_to_policy(
            iam.PolicyStatement(actions=["bedrock:Retrieve"], resources=["*"])
        )
        for fn in [vector_search, whitepaper_lookup, metadata_query, graph_search]:
            fn.grant_invoke(self.agent_role)

        action_groups = [
            self.action_group("vector_search", vector_search, "vector_search.openapi.json"),
            self.action_group("graph_search", graph_search, "graph_search.openapi.json"),
            self.action_group("metadata_query", metadata_query, "metadata_query.openapi.json"),
            self.action_group("whitepaper_lookup", whitepaper_lookup, "whitepaper_lookup.openapi.json"),
        ]

        instructions = """
You are a telecom standards exploration agent. 3GPP chunks are authoritative.
Whitepapers are explanatory only and must not override 3GPP specifications.
For feature questions, first use vector_search, then graph_search to expand related specs,
features, releases, and whitepapers. Use metadata_query for exact section/spec lookups
and whitepaper_lookup for vendor or deployment explanations. Return concise answers with
citations and a Cytoscape-ready graph when relationships are relevant.
""".strip()

        self.agent = bedrock.CfnAgent(
            self,
            "FeatureCloudAgent",
            agent_name=f"{app_name.replace('-', '_')}_agent",
            agent_resource_role_arn=self.agent_role.role_arn,
            foundation_model=foundation_model,
            instruction=instructions,
            idle_session_ttl_in_seconds=1800,
            auto_prepare=True,
            action_groups=action_groups,
            knowledge_bases=[
                bedrock.CfnAgent.AgentKnowledgeBaseProperty(
                    knowledge_base_id=knowledge_base_id,
                    description="Pre-chunked 3GPP source-of-truth specifications and telecom whitepapers with metadata filters.",
                )
            ],
        )

        for fn in [vector_search, whitepaper_lookup, metadata_query, graph_search]:
            lambda_.CfnPermission(
                self,
                f"{fn.node.id}BedrockPermission",
                action="lambda:InvokeFunction",
                function_name=fn.function_name,
                principal="bedrock.amazonaws.com",
                source_account=Aws.ACCOUNT_ID,
                source_arn=f"arn:{Aws.PARTITION}:bedrock:{Aws.REGION}:{Aws.ACCOUNT_ID}:agent/{self.agent.attr_agent_id}",
            )

        self.alias = bedrock.CfnAgentAlias(
            self,
            "LiveAlias",
            agent_id=self.agent.attr_agent_id,
            agent_alias_name="live",
        )

        self.agent_id = self.agent.attr_agent_id
        self.agent_alias_id = self.alias.attr_agent_alias_id
        self.tool_functions = [vector_search, whitepaper_lookup, metadata_query, graph_search]

    def tool_lambda(
        self,
        construct_id: str,
        folder: str,
        *,
        environment: dict[str, str],
        vpc: ec2.IVpc | None = None,
        security_groups: list[ec2.ISecurityGroup] | None = None,
    ) -> lambda_.Function:
        return lambda_.Function(
            self,
            construct_id,
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(ROOT / "lambdas" / "agent_tools" / folder)),
            timeout=Duration.minutes(1),
            memory_size=512,
            environment=environment,
            vpc=vpc,
            security_groups=security_groups,
        )

    def action_group(self, name: str, fn: lambda_.IFunction, schema_file: str) -> bedrock.CfnAgent.AgentActionGroupProperty:
        schema = (ROOT / "agent" / "schemas" / schema_file).read_text(encoding="utf-8")
        return bedrock.CfnAgent.AgentActionGroupProperty(
            action_group_name=name,
            description=f"{name.replace('_', ' ')} tool for telecom standards exploration.",
            action_group_executor=bedrock.CfnAgent.ActionGroupExecutorProperty(lambda_=fn.function_arn),
            api_schema=bedrock.CfnAgent.APISchemaProperty(payload=schema),
        )
