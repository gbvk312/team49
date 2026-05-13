from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_neptune as neptune
from constructs import Construct


class GraphStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, app_name: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "GraphVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
                ec2.SubnetConfiguration(name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24),
            ],
        )

        self.neptune_security_group = ec2.SecurityGroup(
            self,
            "NeptuneSecurityGroup",
            vpc=self.vpc,
            allow_all_outbound=True,
            description="Allows Lambda access to Neptune openCypher",
        )
        self.lambda_security_group = ec2.SecurityGroup(
            self,
            "LambdaGraphSecurityGroup",
            vpc=self.vpc,
            allow_all_outbound=True,
            description="Security group for Lambdas querying Neptune",
        )
        self.neptune_security_group.add_ingress_rule(
            peer=self.lambda_security_group,
            connection=ec2.Port.tcp(8182),
            description="Lambda to Neptune",
        )

        subnet_group = neptune.CfnDBSubnetGroup(
            self,
            "NeptuneSubnetGroup",
            db_subnet_group_description="Private subnets for the 3GPP relationship graph",
            subnet_ids=[subnet.subnet_id for subnet in self.vpc.isolated_subnets],
            db_subnet_group_name=f"{app_name}-neptune-subnets",
        )

        self.cluster = neptune.CfnDBCluster(
            self,
            "NeptuneCluster",
            db_cluster_identifier=f"{app_name}-graph",
            db_subnet_group_name=subnet_group.db_subnet_group_name,
            vpc_security_group_ids=[self.neptune_security_group.security_group_id],
            engine_version="1.4.7.0",
            iam_auth_enabled=True,
            storage_encrypted=True,
            serverless_scaling_configuration=neptune.CfnDBCluster.ServerlessScalingConfigurationProperty(
                min_capacity=1,
                max_capacity=8,
            ),
        )
        self.cluster.apply_removal_policy(RemovalPolicy.RETAIN)
        self.cluster.add_dependency(subnet_group)

        self.instance = neptune.CfnDBInstance(
            self,
            "NeptuneWriterInstance",
            db_cluster_identifier=self.cluster.ref,
            db_instance_class="db.serverless",
            db_subnet_group_name=subnet_group.db_subnet_group_name,
        )
        self.instance.add_dependency(self.cluster)

        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)
        self.vpc.add_gateway_endpoint("DynamoDBEndpoint", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB)

        self.vpc.add_interface_endpoint("BedrockRuntimeEndpoint", service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME)
        self.vpc.add_interface_endpoint("BedrockAgentRuntimeEndpoint", service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT_RUNTIME)
        self.vpc.add_interface_endpoint("TextractEndpoint", service=ec2.InterfaceVpcEndpointAwsService.TEXTRACT)

        self.neptune_endpoint = self.cluster.attr_endpoint
