#!/usr/bin/env python3
import aws_cdk as cdk

from stacks.agent_stack import AgentStack
from stacks.api_stack import ApiStack
from stacks.graph_stack import GraphStack
from stacks.knowledge_stack import KnowledgeStack
from stacks.observability_stack import ObservabilityStack
from stacks.pipeline_stack import PipelineStack
from stacks.storage_stack import StorageStack


app = cdk.App()

app_name = app.node.try_get_context("app_name") or "team49-3gpp"
foundation_model = app.node.try_get_context("foundation_model") or "anthropic.claude-3-5-sonnet-20240620-v1:0"
embedding_model = app.node.try_get_context("embedding_model") or "amazon.titan-embed-text-v2:0"
env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

storage = StorageStack(app, "Team49StorageStack", app_name=app_name, env=env)
knowledge = KnowledgeStack(
    app,
    "Team49KnowledgeStack",
    app_name=app_name,
    chunks_bucket=storage.chunks_bucket,
    embedding_model=embedding_model,
    env=env,
)
graph = GraphStack(app, "Team49GraphStack", app_name=app_name, env=env)
pipeline = PipelineStack(
    app,
    "Team49PipelineStack",
    app_name=app_name,
    raw_bucket=storage.raw_bucket,
    chunks_bucket=storage.chunks_bucket,
    chunks_table=storage.chunks_table,
    features_table=storage.features_table,
    knowledge_base_id=knowledge.knowledge_base_id,
    data_source_id=knowledge.data_source_id,
    neptune_endpoint=graph.neptune_endpoint,
    neptune_security_group=graph.lambda_security_group,
    vpc=graph.vpc,
    foundation_model=foundation_model,
    env=env,
)
agent = AgentStack(
    app,
    "Team49AgentStack",
    app_name=app_name,
    chunks_table=storage.chunks_table,
    features_table=storage.features_table,
    knowledge_base_id=knowledge.knowledge_base_id,
    neptune_endpoint=graph.neptune_endpoint,
    neptune_security_group=graph.lambda_security_group,
    vpc=graph.vpc,
    foundation_model=foundation_model,
    env=env,
)
api = ApiStack(
    app,
    "Team49ApiStack",
    app_name=app_name,
    agent_id=agent.agent_id,
    agent_alias_id=agent.agent_alias_id,
    env=env,
)
ObservabilityStack(
    app,
    "Team49ObservabilityStack",
    app_name=app_name,
    state_machine=pipeline.state_machine,
    api=api.http_api,
    lambdas=[*pipeline.functions, *agent.tool_functions, api.invoker_function],
    env=env,
)

app.synth()
