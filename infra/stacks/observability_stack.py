from aws_cdk import Duration, Stack
from aws_cdk import aws_apigatewayv2 as apigwv2
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        app_name: str,
        state_machine: sfn.IStateMachine,
        api: apigwv2.IHttpApi,
        lambdas: list[lambda_.IFunction],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        dashboard = cloudwatch.Dashboard(self, "FeatureCloudDashboard", dashboard_name=f"{app_name}-dashboard")

        sfn_failed = cloudwatch.Alarm(
            self,
            "StateMachineFailures",
            metric=state_machine.metric_failed(period=Duration.minutes(1)),
            threshold=1,
            evaluation_periods=3,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        sfn_timed_out = cloudwatch.Alarm(
            self,
            "StateMachineTimeouts",
            metric=state_machine.metric_timed_out(period=Duration.minutes(1)),
            threshold=1,
            evaluation_periods=3,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        api_5xx = cloudwatch.Alarm(
            self,
            "ApiServerErrors",
            metric=cloudwatch.Metric(
                namespace="AWS/ApiGateway",
                metric_name="5xx",
                dimensions_map={"ApiId": api.api_id},
                statistic="Sum",
                period=Duration.minutes(1),
            ),
            threshold=1,
            evaluation_periods=3,
            datapoints_to_alarm=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )

        lambda_error_widgets = []
        for fn in lambdas:
            error_rate = cloudwatch.MathExpression(
                expression="IF(invocations > 0, errors * 100 / invocations, 0)",
                using_metrics={
                    "errors": fn.metric_errors(period=Duration.minutes(1)),
                    "invocations": fn.metric_invocations(period=Duration.minutes(1)),
                },
            )
            cloudwatch.Alarm(
                self,
                f"{fn.node.id}ErrorRate",
                metric=error_rate,
                threshold=5,
                evaluation_periods=3,
                datapoints_to_alarm=2,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            )
            lambda_error_widgets.append(fn.metric_errors(period=Duration.minutes(1)))

        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Ingestion workflow failures",
                left=[sfn_failed.metric, sfn_timed_out.metric],
                width=12,
            ),
            cloudwatch.GraphWidget(title="API 5xx", left=[api_5xx.metric], width=12),
            cloudwatch.GraphWidget(title="Lambda errors", left=lambda_error_widgets[:12], width=24),
        )
