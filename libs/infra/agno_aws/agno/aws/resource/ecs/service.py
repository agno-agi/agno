from typing import Any, Dict, List, Optional, Union

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.ec2.security_group import SecurityGroup
from agno.aws.resource.ec2.subnet import Subnet
from agno.aws.resource.ecs.cluster import EcsCluster
from agno.aws.resource.ecs.task_definition import EcsTaskDefinition
from agno.aws.resource.elb.target_group import TargetGroup
from agno.cli.console import print_info
from agno.utils.log import logger


class EcsService(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html
    """

    resource_type: Optional[str] = "Service"
    service_name: str = "ecs"

    # Name for the service.
    name: str
    # Name for the service.
    # Use name if not provided.
    ecs_service_name: Optional[str] = None

    # EcsCluster for the service.
    # Can be
    # - string: The short name or full Amazon Resource Name (ARN) of the cluster
    # - EcsCluster
    # If you do not specify a cluster, the default cluster is assumed.
    cluster: Optional[Union[EcsCluster, str]] = None

    # EcsTaskDefinition for the service.
    # Can be
    # - string: The family and revision (family:revision ) or full ARN of the task definition.
    # - EcsTaskDefinition
    # If a revision isn't specified, the latest ACTIVE revision is used.
    task_definition: Optional[Union[EcsTaskDefinition, str]] = None

    # A load balancer object representing the load balancers to use with your service.
    load_balancers: Optional[List[Dict[str, Any]]] = None

    # We can generate the load_balancers dict using
    # the target_group, target_container_name and target_container_port
    # Target group to attach to a service.
    target_group: Optional[TargetGroup] = None
    # Target container name for the service.
    target_container_name: Optional[str] = None
    target_container_port: Optional[int] = None

    # The network configuration for the service. This parameter is required for task definitions that
    # use the awsvpc network mode to receive their own elastic network interface
    network_configuration: Optional[Dict[str, Any]] = None
    subnets: Optional[List[Union[str, Subnet]]] = None
    security_groups: Optional[List[Union[str, SecurityGroup]]] = None
    assign_public_ip: Optional[bool] = None

    # The configuration for this service to discover and connect to services,
    # and be discovered by, and connected from, other services within a namespace.
    service_connect_configuration: Optional[Dict[str, Any]] = None

    # The details of the service discovery registries to assign to this service.
    service_registries: Optional[List[Dict[str, Any]]] = None
    # The number of instantiations of the specified task definition to place and keep running on your cluster.
    # This is required if schedulingStrategy is REPLICA or isn't specified.
    # If schedulingStrategy is DAEMON then this isn't required.
    desired_count: Optional[int] = None
    # An identifier that you provide to ensure the idempotency of the request. It must be unique and is case-sensitive.
    client_token: Optional[str] = None
    # The infrastructure that you run your service on.
    launch_type: Optional[Union[str, Literal["EC2", "FARGATE", "EXTERNAL"]]] = None
    # The capacity provider strategy to use for the service.
    capacity_provider_strategy: Optional[List[Dict[str, Any]]] = None
    platform_version: Optional[str] = None
    role: Optional[str] = None
    deployment_configuration: Optional[Dict[str, Any]] = None
    placement_constraints: Optional[List[Dict[str, Any]]] = None
    placement_strategy: Optional[List[Dict[str, Any]]] = None
    health_check_grace_period_seconds: Optional[int] = None
    scheduling_strategy: Optional[Literal["REPLICA", "DAEMON"]] = None
    deployment_controller: Optional[Dict[str, Any]] = None
    tags: Optional[List[Dict[str, Any]]] = None
    enable_ecsmanaged_tags: Optional[bool] = None
    propagate_tags: Optional[Literal["TASK_DEFINITION", "SERVICE", "NONE"]] = None
    enable_execute_command: Optional[bool] = None

    force_delete: Optional[bool] = None
    # Force a new deployment of the service on update.
    # By default, deployments aren't forced.
    # You can use this option to start a new deployment with no service
    # definition changes. For example, you can update a service's
    # tasks to use a newer Docker image with the same
    # image/tag combination (my_image:latest ) or
    # to roll Fargate tasks onto a newer platform version.
    force_new_deployment: Optional[bool] = None

    wait_for_create: bool = False

    def get_ecs_service_name(self):
        return self.ecs_service_name or self.name

    def get_ecs_cluster_name(self):
        if self.cluster is not None:
            if isinstance(self.cluster, EcsCluster):
                return self.cluster.get_ecs_cluster_name()
            else:
                return self.cluster

    def get_ecs_task_definition(self):
        if self.task_definition is not None:
            if isinstance(self.task_definition, EcsTaskDefinition):
                return self.task_definition.get_task_family()
            else:
                return self.task_definition

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Create EcsService"""
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        cluster_name = self.get_ecs_cluster_name()
        if cluster_name is not None:
            not_null_args["cluster"] = cluster_name

        network_configuration = self.network_configuration
        if network_configuration is None and (self.subnets is not None or self.security_groups is not None):
            aws_vpc_config: Dict[str, Any] = {}
            if self.subnets is not None:
                subnet_ids = []
                for subnet in self.subnets:
                    if isinstance(subnet, Subnet):
                        subnet_ids.append(subnet.name)
                    elif isinstance(subnet, str):
                        subnet_ids.append(subnet)
                aws_vpc_config["subnets"] = subnet_ids
            if self.security_groups is not None:
                security_group_ids = []
                for sg in self.security_groups:
                    if isinstance(sg, SecurityGroup):
                        security_group_ids.append(sg.get_security_group_id(aws_client))
                    else:
                        security_group_ids.append(sg)
                aws_vpc_config["securityGroups"] = security_group_ids
            if self.assign_public_ip:
                aws_vpc_config["assignPublicIp"] = "ENABLED"
            network_configuration = {"awsvpcConfiguration": aws_vpc_config}
        if network_configuration is not None:
            not_null_args["networkConfiguration"] = network_configuration

        if self.service_connect_configuration is not None:
            not_null_args["serviceConnectConfiguration"] = self.service_connect_configuration

        if self.service_registries is not None:
            not_null_args["serviceRegistries"] = self.service_registries
        if self.desired_count is not None:
            not_null_args["desiredCount"] = self.desired_count
        if self.client_token is not None:
            not_null_args["clientToken"] = self.client_token
        if self.launch_type is not None:
            not_null_args["launchType"] = self.launch_type
        if self.capacity_provider_strategy is not None:
            not_null_args["capacityProviderStrategy"] = self.capacity_provider_strategy
        if self.platform_version is not None:
            not_null_args["platformVersion"] = self.platform_version
        if self.role is not None:
            not_null_args["role"] = self.role
        if self.deployment_configuration is not None:
            not_null_args["deploymentConfiguration"] = self.deployment_configuration
        if self.placement_constraints is not None:
            not_null_args["placementConstraints"] = self.placement_constraints
        if self.placement_strategy is not None:
            not_null_args["placementStrategy"] = self.placement_strategy
        if self.health_check_grace_period_seconds is not None:
            not_null_args["healthCheckGracePeriodSeconds"] = self.health_check_grace_period_seconds
        if self.scheduling_strategy is not None:
            not_null_args["schedulingStrategy"] = self.scheduling_strategy
        if self.deployment_controller is not None:
            not_null_args["deploymentController"] = self.deployment_controller
        if self.tags is not None:
            not_null_args["tags"] = self.tags
        if self.enable_ecsmanaged_tags is not None:
            not_null_args["enableECSManagedTags"] = self.enable_ecsmanaged_tags
        if self.propagate_tags is not None:
            not_null_args["propagateTags"] = self.propagate_tags
        if self.enable_execute_command is not None:
            not_null_args["enableExecuteCommand"] = self.enable_execute_command

        if self.load_balancers is not None:
            not_null_args["loadBalancers"] = self.load_balancers
        elif self.target_group is not None and self.target_container_name is not None:
            not_null_args["loadBalancers"] = [
                {
                    "targetGroupArn": self.target_group.get_arn(aws_client),
                    "containerName": self.target_container_name,
                    "containerPort": self.target_container_port,
                }
            ]

        # Register EcsService
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.create_service(
                serviceName=self.get_ecs_service_name(),
                taskDefinition=self.get_ecs_task_definition(),
                **not_null_args,
            )
            logger.debug(f"EcsService: {create_response}")
            resource_dict = create_response.get("service", {})

            # Validate resource creation
            if resource_dict is not None:
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def post_create(self, aws_client: AwsApiClient) -> bool:
        # Wait for EcsService to be created
        if self.wait_for_create:
            try:
                cluster_name = self.get_ecs_cluster_name()
                if cluster_name is not None:
                    print_info(f"Waiting for {self.get_resource_type()} to be available.")
                    waiter = self.get_service_client(aws_client).get_waiter("services_stable")
                    waiter.wait(
                        cluster=cluster_name,
                        services=[self.get_ecs_service_name()],
                        WaiterConfig={
                            "Delay": self.waiter_delay,
                            "MaxAttempts": self.waiter_max_attempts,
                        },
                    )
                else:
                    logger.warning("Skipping waiter, no Service found")
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Read EcsService"""
        from botocore.exceptions import ClientError

        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        cluster_name = self.get_ecs_cluster_name()
        if cluster_name is not None:
            not_null_args["cluster"] = cluster_name

        service_client = self.get_service_client(aws_client)
        try:
            service_name: str = self.get_ecs_service_name()
            describe_response = service_client.describe_services(services=[service_name], **not_null_args)
            logger.debug(f"EcsService: {describe_response}")
            resource_list = describe_response.get("services", None)

            if resource_list is not None and isinstance(resource_list, list):
                for resource in resource_list:
                    _service_name: str = resource.get("serviceName", None)
                    if _service_name == service_name:
                        _service_status = resource.get("status", None)
                        if _service_status == "ACTIVE":
                            self.active_resource = resource
                            break
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Delete EcsService"""
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        cluster_name = self.get_ecs_cluster_name()
        if cluster_name is not None:
            not_null_args["cluster"] = cluster_name
        if self.force_delete is not None:
            not_null_args["force"] = self.force_delete

        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        try:
            delete_response = service_client.delete_service(
                service=self.get_ecs_service_name(),
                **not_null_args,
            )
            logger.debug(f"EcsService: {delete_response}")
            return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        # Wait for EcsService to be deleted
        if self.wait_for_delete:
            try:
                cluster_name = self.get_ecs_cluster_name()
                if cluster_name is not None:
                    print_info(f"Waiting for {self.get_resource_type()} to be deleted.")
                    waiter = self.get_service_client(aws_client).get_waiter("services_inactive")
                    waiter.wait(
                        cluster=cluster_name,
                        services=[self.get_ecs_service_name()],
                        WaiterConfig={
                            "Delay": self.waiter_delay,
                            "MaxAttempts": self.waiter_max_attempts,
                        },
                    )
                else:
                    logger.warning("Skipping waiter, no Service found")
            except Exception as e:
                logger.error("Waiter failed.")
                logger.error(e)
        return True

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Updates the EcsService

        Args:
            aws_client: The AwsApiClient for the current cluster
        """

        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}

        cluster_name = self.get_ecs_cluster_name()
        if cluster_name is not None:
            not_null_args["cluster"] = cluster_name

        network_configuration = self.network_configuration
        if network_configuration is None and (self.subnets is not None or self.security_groups is not None):
            aws_vpc_config: Dict[str, Any] = {}
            if self.subnets is not None:
                subnet_ids = []
                for subnet in self.subnets:
                    if isinstance(subnet, Subnet):
                        subnet_ids.append(subnet.name)
                    elif isinstance(subnet, str):
                        subnet_ids.append(subnet)
                aws_vpc_config["subnets"] = subnet_ids
            if self.security_groups is not None:
                security_group_ids = []
                for sg in self.security_groups:
                    if isinstance(sg, SecurityGroup):
                        security_group_ids.append(sg.get_security_group_id(aws_client))
                    else:
                        security_group_ids.append(sg)
                aws_vpc_config["securityGroups"] = security_group_ids
            if self.assign_public_ip:
                aws_vpc_config["assignPublicIp"] = "ENABLED"
            network_configuration = {"awsvpcConfiguration": aws_vpc_config}
        if self.network_configuration is not None:
            not_null_args["networkConfiguration"] = network_configuration

        if self.desired_count is not None:
            not_null_args["desiredCount"] = self.desired_count
        if self.capacity_provider_strategy is not None:
            not_null_args["capacityProviderStrategy"] = self.capacity_provider_strategy
        if self.deployment_configuration is not None:
            not_null_args["deploymentConfiguration"] = self.deployment_configuration
        if self.placement_constraints is not None:
            not_null_args["placementConstraints"] = self.placement_constraints
        if self.placement_strategy is not None:
            not_null_args["placementStrategy"] = self.placement_strategy
        if self.platform_version is not None:
            not_null_args["platformVersion"] = self.platform_version
        if self.force_new_deployment is not None:
            not_null_args["forceNewDeployment"] = self.force_new_deployment
        if self.health_check_grace_period_seconds is not None:
            not_null_args["healthCheckGracePeriodSeconds"] = self.health_check_grace_period_seconds
        if self.enable_execute_command is not None:
            not_null_args["enableExecuteCommand"] = self.enable_execute_command
        if self.enable_ecsmanaged_tags is not None:
            not_null_args["enableECSManagedTags"] = self.enable_ecsmanaged_tags
        if self.load_balancers is not None:
            not_null_args["loadBalancers"] = self.load_balancers
        if self.propagate_tags is not None:
            not_null_args["propagateTags"] = self.propagate_tags
        if self.service_registries is not None:
            not_null_args["serviceRegistries"] = self.service_registries

        try:
            # Update EcsService
            service_client = self.get_service_client(aws_client)
            update_response = service_client.update_service(
                service=self.get_ecs_service_name(),
                taskDefinition=self.get_ecs_task_definition(),
                **not_null_args,
            )
            logger.debug(f"update_response: {update_response}")

            self.active_resource = update_response.get("service", None)
            if self.active_resource is not None:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} updated")
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be updated.")
            logger.error("Please try again or update resources manually.")
            logger.error(e)
        return False
