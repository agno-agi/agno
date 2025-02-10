from textwrap import dedent
from typing import Any, Dict, List, Optional

from typing_extensions import Literal

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.ecs.container import EcsContainer
from agno.aws.resource.ecs.volume import EcsVolume
from agno.aws.resource.iam.policy import IamPolicy
from agno.aws.resource.iam.role import IamRole
from agno.cli.console import print_info
from agno.utils.log import logger


class EcsTaskDefinition(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs/client/register_task_definition.html
    """

    resource_type: Optional[str] = "TaskDefinition"
    service_name: str = "ecs"

    # Name of the task definition.
    # Used as task definition family.
    name: str
    # The family for a task definition.
    # Use name as family if not provided
    # You can use it track multiple versions of the same task definition.
    # The family is used as a name for your task definition.
    family: Optional[str] = None
    # Networking mode to use for the containers in the task.
    # The valid values are none, bridge, awsvpc, and host.
    # If no network mode is specified, the default is bridge.
    network_mode: Optional[Literal["bridge", "host", "awsvpc", "none"]] = None
    # A list of container definitions that describe the different containers that make up the task.
    containers: Optional[List[EcsContainer]] = None
    volumes: Optional[List[EcsVolume]] = None
    placement_constraints: Optional[List[Dict[str, Any]]] = None
    requires_compatibilities: Optional[List[str]] = None
    cpu: Optional[str] = None
    memory: Optional[str] = None
    tags: Optional[List[Dict[str, str]]] = None
    pid_mode: Optional[Literal["host", "task"]] = None
    ipc_mode: Optional[Literal["host", "task", "none"]] = None
    proxy_configuration: Optional[Dict[str, Any]] = None
    inference_accelerators: Optional[List[Dict[str, Any]]] = None
    ephemeral_storage: Optional[Dict[str, Any]] = None
    runtime_platform: Optional[Dict[str, Any]] = None

    # Amazon ECS IAM roles
    # The short name or full Amazon Resource Name (ARN) of the IAM role that containers in this task can assume.
    # The permissions granted in this IAM role are assumed by the containers running in the task.
    # For permissions that Amazon ECS needs to pull container images, see execution_role_arn
    # If your containerized applications need to call AWS APIs, they must sign their
    # AWS API requests with AWS credentials, and a task IAM role provides a strategy for managing credentials
    # for your applications to use
    task_role_arn: Optional[str] = None
    # If task_role_arn is None, a default role is created if create_task_role is True
    create_task_role: bool = True
    # Name for the default role when task_role_arn is None, use "name-task-role" if not provided
    task_role_name: Optional[str] = None
    # Provide a list of policy ARNs to attach to the role
    add_policy_arns_to_task_role: Optional[List[str]] = None
    # Provide a list of IamPolicy to attach to the task role
    add_policies_to_task_role: Optional[List[IamPolicy]] = None
    # Add bedrock access to task role
    add_bedrock_access_to_task: bool = False
    # Add ecs_exec_policy to task role
    add_exec_access_to_task: bool = False
    # Add secret access to task role
    add_secret_access_to_task: bool = False
    # Add s3 access to task role
    add_s3_access_to_task: bool = False

    # The Amazon Resource Name (ARN) of the task execution role that grants the Amazon ECS container agent permission
    # to make Amazon Web Services API calls on your behalf. The task execution IAM role is required depending on the
    # requirements of your task.
    execution_role_arn: Optional[str] = None
    # If execution_role_arn is None, a default role is created if create_execution_role is True
    create_execution_role: bool = True
    # Name for the default role when execution_role_arn is None, use "name-execution-role" if not provided
    execution_role_name: Optional[str] = None
    # Provide a list of policy ARNs to attach to the role
    add_policy_arns_to_execution_role: Optional[List[str]] = None
    # Provide a list of IamPolicy to attach to the execution role
    add_policies_to_execution_role: Optional[List[IamPolicy]] = None
    # Add policy to read secrets to execution role
    add_secret_access_to_ecs: bool = False

    def get_task_family(self):
        return self.family or self.name

    def _create(self, aws_client: AwsApiClient) -> bool:
        """Create EcsTaskDefinition"""
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Get task role arn
        task_role_arn = self.task_role_arn
        if task_role_arn is None and self.create_task_role:
            # Create the IamRole and get task_role_arn
            task_role = self.get_task_role()
            try:
                task_role.create(aws_client)
                task_role_arn = task_role.read(aws_client).arn
                print_info(f"ARN for {task_role.name}: {task_role_arn}")
            except Exception as e:
                logger.error("IamRole creation failed, please fix and try again")
                logger.error(e)
                return False

        # Step 2: Get execution role arn
        execution_role_arn = self.execution_role_arn
        if execution_role_arn is None and self.create_execution_role:
            # Create the IamRole and get execution_role_arn
            execution_role = self.get_execution_role()
            try:
                execution_role.create(aws_client)
                execution_role_arn = execution_role.read(aws_client).arn
                print_info(f"ARN for {execution_role.name}: {execution_role_arn}")
            except Exception as e:
                logger.error("IamRole creation failed, please fix and try again")
                logger.error(e)
                return False

        # create a dict of args which are not null, otherwise aws type validation fails
        not_null_args: Dict[str, Any] = {}
        if task_role_arn is not None:
            not_null_args["taskRoleArn"] = task_role_arn
        if execution_role_arn is not None:
            not_null_args["executionRoleArn"] = execution_role_arn
        if self.network_mode is not None:
            not_null_args["networkMode"] = self.network_mode
        if self.containers is not None:
            container_definitions = [c.get_container_definition(aws_client=aws_client) for c in self.containers]
            not_null_args["containerDefinitions"] = container_definitions
        if self.volumes is not None:
            volume_definitions = [v.get_volume_definition() for v in self.volumes]
            not_null_args["volumes"] = volume_definitions
        if self.placement_constraints is not None:
            not_null_args["placementConstraints"] = self.placement_constraints
        if self.requires_compatibilities is not None:
            not_null_args["requiresCompatibilities"] = self.requires_compatibilities
        if self.cpu is not None:
            not_null_args["cpu"] = self.cpu
        if self.memory is not None:
            not_null_args["memory"] = self.memory
        if self.tags is not None:
            not_null_args["tags"] = self.tags
        if self.pid_mode is not None:
            not_null_args["pidMode"] = self.pid_mode
        if self.ipc_mode is not None:
            not_null_args["ipcMode"] = self.ipc_mode
        if self.proxy_configuration is not None:
            not_null_args["proxyConfiguration"] = self.proxy_configuration
        if self.inference_accelerators is not None:
            not_null_args["inferenceAccelerators"] = self.inference_accelerators
        if self.ephemeral_storage is not None:
            not_null_args["ephemeralStorage"] = self.ephemeral_storage
        if self.runtime_platform is not None:
            not_null_args["runtimePlatform"] = self.runtime_platform

        # Register EcsTaskDefinition
        service_client = self.get_service_client(aws_client)
        try:
            create_response = service_client.register_task_definition(
                family=self.get_task_family(),
                **not_null_args,
            )
            logger.debug(f"EcsTaskDefinition: {create_response}")
            resource_dict = create_response.get("taskDefinition", {})

            # Validate resource creation
            if resource_dict is not None:
                self.active_resource = create_response
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be created.")
            logger.error(e)
        return False

    def _read(self, aws_client: AwsApiClient) -> Optional[Any]:
        """Read EcsTaskDefinition"""
        from botocore.exceptions import ClientError

        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")
        service_client = self.get_service_client(aws_client)
        try:
            describe_response = service_client.describe_task_definition(taskDefinition=self.get_task_family())
            logger.debug(f"EcsTaskDefinition: {describe_response}")
            resource = describe_response.get("taskDefinition", None)
            if resource is not None:
                # compare the task definition with the current state
                # if there is a difference, create a new task definition
                # TODO: fix the task_definition_up_to_date function
                # if self.task_definition_up_to_date(task_definition=resource):
                self.active_resource = resource
        except ClientError as ce:
            logger.debug(f"ClientError: {ce}")
        except Exception as e:
            logger.error(f"Error reading {self.get_resource_type()}.")
            logger.error(e)
        return self.active_resource

    def _delete(self, aws_client: AwsApiClient) -> bool:
        """Delete EcsTaskDefinition"""
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        # Step 1: Delete the task role
        if self.task_role_arn is None and self.create_task_role:
            task_role = self.get_task_role()
            try:
                task_role.delete(aws_client)
            except Exception as e:
                logger.error("IamRole deletion failed, please try again or delete manually")
                logger.error(e)

        # Step 2: Delete the execution role
        if self.execution_role_arn is None and self.create_execution_role:
            execution_role = self.get_execution_role()
            try:
                execution_role.delete(aws_client)
            except Exception as e:
                logger.error("IamRole deletion failed, please try again or delete manually")
                logger.error(e)

        service_client = self.get_service_client(aws_client)
        self.active_resource = None
        try:
            # Get the task definition revisions
            list_response = service_client.list_task_definitions(familyPrefix=self.get_task_family(), sort="DESC")
            logger.debug(f"EcsTaskDefinition: {list_response}")
            task_definition_arns = list_response.get("taskDefinitionArns", [])
            if task_definition_arns:
                # Delete all revisions
                for task_definition_arn in task_definition_arns:
                    service_client.deregister_task_definition(taskDefinition=task_definition_arn)
                print_info(f"EcsTaskDefinition deleted: {self.get_resource_name()}")
                return True
        except Exception as e:
            logger.error(f"{self.get_resource_type()} could not be deleted.")
            logger.error("Please try again or delete resources manually.")
            logger.error(e)
        return False

    def _update(self, aws_client: AwsApiClient) -> bool:
        """Update EcsTaskDefinition"""
        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        return self._create(aws_client)

    def get_task_role(self) -> IamRole:
        policy_arns = [
            "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
            "arn:aws:iam::aws:policy/CloudWatchFullAccess",
        ]
        if self.add_policy_arns_to_task_role is not None and isinstance(self.add_policy_arns_to_task_role, list):
            policy_arns.extend(self.add_policy_arns_to_task_role)

        policies = []
        if self.add_bedrock_access_to_task:
            bedrock_access_policy = IamPolicy(
                name=f"{self.name}-bedrock-access-policy",
                policy_document=dedent(
                    """\
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "bedrock:*",
                            "Resource": "*"
                        }
                    ]
                }
                """
                ),
            )
            policies.append(bedrock_access_policy)
        if self.add_exec_access_to_task:
            ecs_exec_policy = IamPolicy(
                name=f"{self.name}-task-exec-policy",
                policy_document=dedent(
                    """\
                {
                   "Version": "2012-10-17",
                   "Statement": [
                       {
                       "Effect": "Allow",
                       "Action": [
                            "ssmmessages:CreateControlChannel",
                            "ssmmessages:CreateDataChannel",
                            "ssmmessages:OpenControlChannel",
                            "ssmmessages:OpenDataChannel"
                       ],
                      "Resource": "*"
                      }
                   ]
                }
                """
                ),
            )
            policies.append(ecs_exec_policy)
        if self.add_secret_access_to_task:
            policy_arns.append("arn:aws:iam::aws:policy/SecretsManagerReadWrite")
        if self.add_s3_access_to_task:
            policy_arns.append("arn:aws:iam::aws:policy/AmazonS3FullAccess")
        if self.add_policies_to_task_role:
            policies.extend(self.add_policies_to_task_role)

        return IamRole(
            name=self.task_role_name or f"{self.name}-task-role",
            assume_role_policy_document=dedent(
                """\
            {
              "Version": "2012-10-17",
              "Statement": [
                {
                  "Effect": "Allow",
                  "Principal": {
                    "Service": "ecs-tasks.amazonaws.com"
                  },
                  "Action": "sts:AssumeRole"
                }
              ]
            }
            """
            ),
            policies=policies,
            policy_arns=policy_arns,
        )

    def get_execution_role(self) -> IamRole:
        policy_arns = [
            "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
            "arn:aws:iam::aws:policy/CloudWatchFullAccess",
        ]
        if self.add_policy_arns_to_execution_role is not None and isinstance(
            self.add_policy_arns_to_execution_role, list
        ):
            policy_arns.extend(self.add_policy_arns_to_execution_role)

        policies = []
        if self.add_secret_access_to_ecs:
            ecs_secret_policy = IamPolicy(
                name=f"{self.name}-ecs-secret-policy",
                policy_document=dedent(
                    """\
                {
                   "Version": "2012-10-17",
                   "Statement": [
                       {
                       "Effect": "Allow",
                       "Action": [
                            "secretsmanager:GetSecretValue",
                            "secretsmanager:DescribeSecret",
                            "secretsmanager:ListSecretVersionIds"
                       ],
                      "Resource": "*"
                      }
                   ]
                }
                """
                ),
            )
            policies.append(ecs_secret_policy)
        if self.add_policies_to_execution_role:
            policies.extend(self.add_policies_to_execution_role)

        return IamRole(
            name=self.execution_role_name or f"{self.name}-execution-role",
            assume_role_policy_document=dedent(
                """\
            {
              "Version": "2012-10-17",
              "Statement": [
                {
                  "Effect": "Allow",
                  "Principal": {
                    "Service": "ecs-tasks.amazonaws.com"
                  },
                  "Action": "sts:AssumeRole"
                }
              ]
            }
            """
            ),
            policies=policies,
            policy_arns=policy_arns,
        )

    # def task_definition_up_to_date(self, task_definition: Dict[str, Any]) -> bool:
    #     """Return True if task_definition from the cluster matches the current state"""
    #
    #     # Validate container definitions
    #     if self.containers is not None:
    #         container_definitions_from_api = task_definition.get("containerDefinitions")
    #         # Compare the container definitions from the api with the current containers
    #         # The order of the container definitions should also match
    #         if container_definitions_from_api is not None and len(container_definitions_from_api) == len(
    #             self.containers
    #         ):
    #             for i, container in enumerate(self.containers):
    #                 if not container.container_definition_up_to_date(
    #                     container_definition=container_definitions_from_api[i]
    #                 ):
    #                     logger.debug("Container definitions not up to date")
    #                     return False
    #         else:
    #             logger.debug("Container definitions not up to date")
    #             return False
    #
    #     # Validate volumes
    #     if self.volumes is not None:
    #         volume_definitions_from_api = task_definition.get("volumes")
    #         # Compare the volume definitions from the api with the current volumes
    #         # The order of the volume definitions should also match
    #         if volume_definitions_from_api is not None and len(volume_definitions_from_api) == len(
    #             self.volumes
    #         ):
    #             for i, volume in enumerate(self.volumes):
    #                 if not volume.volume_definition_up_to_date(
    #                     volume_definition=volume_definitions_from_api[i]
    #                 ):
    #                     logger.debug("Volume definitions not up to date")
    #                     return False
    #         else:
    #             logger.debug("Volume definitions not up to date")
    #             return False
    #
    #     # Validate other properties
    #     if self.task_role_arn is not None:
    #         if self.task_role_arn != task_definition.get("taskRoleArn"):
    #             logger.debug("{} != {}".format(self.task_role_arn, task_definition.get("taskRoleArn")))
    #             return False
    #     if self.execution_role_arn is not None:
    #         if self.execution_role_arn != task_definition.get("executionRoleArn"):
    #             logger.debug(
    #                 "{} != {}".format(self.execution_role_arn, task_definition.get("executionRoleArn"))
    #             )
    #             return False
    #     if self.network_mode is not None:
    #         if self.network_mode != task_definition.get("networkMode"):
    #             logger.debug("{} != {}".format(self.network_mode, task_definition.get("networkMode")))
    #             return False
    #     if self.placement_constraints is not None:
    #         if self.placement_constraints != task_definition.get("placementConstraints"):
    #             logger.debug(
    #                 "{} != {}".format(
    #                     self.placement_constraints,
    #                     task_definition.get("placementConstraints"),
    #                 )
    #             )
    #             return False
    #     if self.requires_compatibilities is not None:
    #         if self.requires_compatibilities != task_definition.get("requiresCompatibilities"):
    #             logger.debug(
    #                 "{} != {}".format(
    #                     self.requires_compatibilities,
    #                     task_definition.get("requiresCompatibilities"),
    #                 )
    #             )
    #             return False
    #     if self.cpu is not None:
    #         if self.cpu != task_definition.get("cpu"):
    #             logger.debug("{} != {}".format(self.cpu, task_definition.get("cpu")))
    #             return False
    #     if self.memory is not None:
    #         if self.memory != task_definition.get("memory"):
    #             logger.debug("{} != {}".format(self.memory, task_definition.get("memory")))
    #             return False
    #     if self.tags is not None:
    #         if self.tags != task_definition.get("tags"):
    #             logger.debug("{} != {}".format(self.tags, task_definition.get("tags")))
    #             return False
    #     if self.pid_mode is not None:
    #         if self.pid_mode != task_definition.get("pidMode"):
    #             logger.debug("{} != {}".format(self.pid_mode, task_definition.get("pidMode")))
    #             return False
    #     if self.ipc_mode is not None:
    #         if self.ipc_mode != task_definition.get("ipcMode"):
    #             logger.debug("{} != {}".format(self.ipc_mode, task_definition.get("ipcMode")))
    #             return False
    #     if self.proxy_configuration is not None:
    #         if self.proxy_configuration != task_definition.get("proxyConfiguration"):
    #             logger.debug(
    #                 "{} != {}".format(
    #                     self.proxy_configuration,
    #                     task_definition.get("proxyConfiguration"),
    #                 )
    #             )
    #             return False
    #     if self.inference_accelerators is not None:
    #         if self.inference_accelerators != task_definition.get("inferenceAccelerators"):
    #             logger.debug(
    #                 "{} != {}".format(
    #                     self.inference_accelerators,
    #                     task_definition.get("inferenceAccelerators"),
    #                 )
    #             )
    #             return False
    #     if self.ephemeral_storage is not None:
    #         if self.ephemeral_storage != task_definition.get("ephemeralStorage"):
    #             logger.debug(
    #                 "{} != {}".format(self.ephemeral_storage, task_definition.get("ephemeralStorage"))
    #             )
    #             return False
    #     if self.runtime_platform is not None:
    #         if self.runtime_platform != task_definition.get("runtimePlatform"):
    #             logger.debug("{} != {}".format(self.runtime_platform, task_definition.get("runtimePlatform")))
    #             return False
    #
    #     return True
