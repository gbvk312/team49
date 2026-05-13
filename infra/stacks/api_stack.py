from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct


ROOT = Path(__file__).resolve().parents[2]


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        agent_id: str,
        agent_alias_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.invoker_function = lambda_.Function(
            self,
            "AgentInvoker",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(ROOT / "lambdas" / "agent_invoker")),
            timeout=Duration.seconds(30),
            memory_size=512,
            environment={"AGENT_ID": agent_id, "AGENT_ALIAS_ID": agent_alias_id, "CORS_ORIGIN": "*"},
        )
        self.invoker_function.add_to_role_policy(
            iam.PolicyStatement(actions=["bedrock:InvokeAgent"], resources=["*"])
        )

        self.http_api = apigwv2.HttpApi(
            self,
            "FeatureCloudApi",
            api_name=f"{app_name}-api",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_headers=["Content-Type", "Authorization"],
                allow_methods=[apigwv2.CorsHttpMethod.OPTIONS, apigwv2.CorsHttpMethod.POST],
                allow_origins=["*"],
            ),
        )
        self.http_api.add_routes(
            path="/ask",
            methods=[apigwv2.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("AskIntegration", self.invoker_function),
        )

        CfnOutput(self, "HttpApiUrl", value=self.http_api.api_endpoint)
