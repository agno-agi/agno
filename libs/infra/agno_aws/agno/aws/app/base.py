from typing import TYPE_CHECKING, Any, Dict, List, Optional

from pydantic import Field, field_validator
from pydantic_core.core_schema import ValidationInfo

from agno.aws.context import AwsBuildContext
from agno.infra.app import InfraApp
from agno.infra.context import ContainerContext
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.aws.resource.base import AwsResource
    from agno.aws.resource.ec2.security_group import SecurityGroup
    from agno.aws.resource.ecs.cluster import EcsCluster
    from agno.aws.resource.ecs.container import EcsContainer
    from agno.aws.resource.ecs.service import EcsService
    from agno.aws.resource.ecs.task_definition import EcsTaskDefinition
    from agno.aws.resource.elb.listener import Listener
    from agno.aws.resource.elb.load_balancer import LoadBalancer
    from agno.aws.resource.elb.target_group import TargetGroup


class AwsApp(InfraApp):
    # -*- Workspace Configuration
    # Path to the workspace directory inside the container
    workspace_dir_container_path: str = "/app"

    # -*- Networking Configuration
    # List of subnets for the app: Type: Union[str, Subnet]
    # Added to the load balancer, target group, and ECS service
    subnets: Optional[List[Any]] = None

    # -*- ECS Configuration
    ecs_cluster: Optional[Any] = None
    # Create a cluster if ecs_cluster is None
    create_ecs_cluster: bool = True
    # Name of the ECS cluster
    ecs_cluster_name: Optional[str] = None
    ecs_launch_type: str = "FARGATE"
    ecs_task_cpu: str = "1024"
    ecs_task_memory: str = "2048"
    ecs_service_count: int = 1
    ecs_enable_service_connect: bool = False
    ecs_service_connect_protocol: Optional[str] = None
    ecs_service_connect_namespace: str = "default"
    assign_public_ip: Optional[bool] = None
    ecs_bedrock_access: bool = True
    ecs_exec_access: bool = True
    ecs_secret_access: bool = True
    ecs_s3_access: bool = True

    # -*- Security Group Configuration
    # List of security groups for the ECS Service. Type: SecurityGroup
    security_groups: Optional[List[Any]] = None
    # If create_security_groups=True,
    # Create security groups for the app and load balancer
    create_security_groups: bool = True
    # inbound_security_groups to add to the app security group
    inbound_security_groups: Optional[List[Any]] = None
    # inbound_security_group_ids to add to the app security group
    inbound_security_group_ids: Optional[List[str]] = None

    # -*- LoadBalancer Configuration
    load_balancer: Optional[Any] = None
    # Create a load balancer if load_balancer is None
    create_load_balancer: bool = False
    # Enable HTTPS on the load balancer
    load_balancer_enable_https: bool = False
    # ACM certificate for HTTPS
    # load_balancer_certificate or load_balancer_certificate_arn
    # is required if enable_https is True
    load_balancer_certificate: Optional[Any] = None
    # ARN of the certificate for HTTPS, required if enable_https is True
    load_balancer_certificate_arn: Optional[str] = None
    # Security groups for the load balancer: List[SecurityGroup]
    # The App creates a security group for the load balancer if:
    # load_balancer_security_groups is None
    # and create_load_balancer is True
    # and create_security_groups is True
    load_balancer_security_groups: Optional[List[Any]] = None

    # -*- Listener Configuration
    listeners: Optional[List[Any]] = None
    # Create a listener if listener is None
    create_listeners: Optional[bool] = Field(None, validate_default=True)

    # -*- TargetGroup Configuration
    target_group: Optional[Any] = None
    # Create a target group if target_group is None
    create_target_group: Optional[bool] = Field(None, validate_default=True)
    # HTTP or HTTPS. Recommended to use HTTP because HTTPS is handled by the load balancer
    target_group_protocol: str = "HTTP"
    # Port number for the target group
    # If target_group_port is None, then use container_port
    target_group_port: Optional[int] = None
    target_group_type: str = "ip"
    health_check_protocol: Optional[str] = None
    health_check_port: Optional[str] = None
    health_check_enabled: Optional[bool] = None
    health_check_path: Optional[str] = None
    health_check_interval_seconds: Optional[int] = None
    health_check_timeout_seconds: Optional[int] = None
    healthy_threshold_count: Optional[int] = None
    unhealthy_threshold_count: Optional[int] = None

    # -*- Add NGINX reverse proxy
    enable_nginx: bool = False
    nginx_image: Optional[Any] = None
    nginx_image_name: str = "nginx"
    nginx_image_tag: str = "1.25.2-alpine"
    nginx_container_port: int = 80

    @field_validator("create_listeners", mode="before")
    def update_create_listeners(cls, create_listeners, info: ValidationInfo):
        if create_listeners:
            return create_listeners

        # If create_listener is False, then create a listener if create_load_balancer is True
        return info.data.get("create_load_balancer", None)

    @field_validator("create_target_group", mode="before")
    def update_create_target_group(cls, create_target_group, info: ValidationInfo):
        if create_target_group:
            return create_target_group

        # If create_target_group is False, then create a target group if create_load_balancer is True
        return info.data.get("create_load_balancer", None)

    def get_container_context(self) -> Optional[ContainerContext]:
        logger.debug("Building ContainerContext")

        if self.container_context is not None:  # type: ignore
            return self.container_context  # type: ignore

        workspace_name = self.workspace_name
        if workspace_name is None:
            raise Exception("Could not determine workspace_name")

        workspace_root_in_container = self.workspace_dir_container_path
        if workspace_root_in_container is None:
            raise Exception("Could not determine workspace_root in container")

        workspace_parent_paths = workspace_root_in_container.split("/")[0:-1]
        workspace_parent_in_container = "/".join(workspace_parent_paths)

        self.container_context = ContainerContext(
            workspace_name=workspace_name,
            workspace_root=workspace_root_in_container,
            workspace_parent=workspace_parent_in_container,
        )

        if self.workspace_settings is not None and self.workspace_settings.ws_schema is not None:
            self.container_context.workspace_schema = self.workspace_settings.ws_schema  # type: ignore

        if self.requirements_file is not None:
            self.container_context.requirements_file = f"{workspace_root_in_container}/{self.requirements_file}"  # type: ignore

        return self.container_context

    def get_container_env(self, container_context: ContainerContext, build_context: AwsBuildContext) -> Dict[str, str]:
        from agno.constants import (
            AGNO_RUNTIME_ENV_VAR,
            PYTHONPATH_ENV_VAR,
            REQUIREMENTS_FILE_PATH_ENV_VAR,
            WORKSPACE_ID_ENV_VAR,
            WORKSPACE_ROOT_ENV_VAR,
        )

        # Container Environment
        container_env: Dict[str, str] = self.container_env or {}
        container_env.update(
            {
                "INSTALL_REQUIREMENTS": str(self.install_requirements),
                "PRINT_ENV_ON_LOAD": str(self.print_env_on_load),
                AGNO_RUNTIME_ENV_VAR: "ecs",
                REQUIREMENTS_FILE_PATH_ENV_VAR: container_context.requirements_file or "",
                WORKSPACE_ROOT_ENV_VAR: container_context.workspace_root or "",
            }
        )

        try:
            if container_context.workspace_schema is not None:
                if container_context.workspace_schema.id_workspace is not None:
                    container_env[WORKSPACE_ID_ENV_VAR] = str(container_context.workspace_schema.id_workspace) or ""
        except Exception:
            pass

        if self.set_python_path:
            python_path = self.python_path
            if python_path is None:
                python_path = container_context.workspace_root
                if self.add_python_paths is not None:
                    python_path = "{}:{}".format(python_path, ":".join(self.add_python_paths))
            if python_path is not None:
                container_env[PYTHONPATH_ENV_VAR] = python_path

        # Set aws region and profile
        self.set_aws_env_vars(env_dict=container_env, aws_region=build_context.aws_region)

        # Update the container env using env_file
        env_data_from_file = self.get_env_file_data()
        if env_data_from_file is not None:
            container_env.update({k: str(v) for k, v in env_data_from_file.items() if v is not None})

        # Update the container env using secrets_file
        secret_data_from_file = self.get_secret_file_data()
        if secret_data_from_file is not None:
            container_env.update({k: str(v) for k, v in secret_data_from_file.items() if v is not None})

        # Update the container env with user provided env_vars
        # this overwrites any existing variables with the same key
        if self.env_vars is not None and isinstance(self.env_vars, dict):
            container_env.update({k: v for k, v in self.env_vars.items() if v is not None})

        # logger.debug("Container Environment: {}".format(container_env))
        return container_env

    def get_load_balancer_security_groups(self) -> Optional[List["SecurityGroup"]]:
        from agno.aws.resource.ec2.security_group import InboundRule, SecurityGroup

        load_balancer_security_groups: Optional[List[SecurityGroup]] = self.load_balancer_security_groups
        if load_balancer_security_groups is None:
            # Create security group for the load balancer
            if self.create_load_balancer and self.create_security_groups:
                load_balancer_security_groups = []
                lb_sg = SecurityGroup(
                    name=f"{self.get_app_name()}-lb-security-group",
                    description=f"Security group for {self.get_app_name()} load balancer",
                    inbound_rules=[
                        InboundRule(
                            description="Allow HTTP traffic from the internet",
                            port=80,
                            cidr_ip="0.0.0.0/0",
                        ),
                    ],
                )
                if self.load_balancer_enable_https:
                    if lb_sg.inbound_rules is None:
                        lb_sg.inbound_rules = []
                    lb_sg.inbound_rules.append(
                        InboundRule(
                            description="Allow HTTPS traffic from the internet",
                            port=443,
                            cidr_ip="0.0.0.0/0",
                        )
                    )
                load_balancer_security_groups.append(lb_sg)
        return load_balancer_security_groups

    def security_group_definition(self) -> "SecurityGroup":
        from agno.aws.resource.ec2.security_group import InboundRule, SecurityGroup
        from agno.aws.resource.reference import AwsReference

        # Create security group for the app
        app_sg = SecurityGroup(
            name=f"{self.get_app_name()}-security-group",
            description=f"Security group for {self.get_app_name()}",
        )

        # Add inbound rules for the app security group
        # Allow traffic from the load balancer security groups
        load_balancer_security_groups = self.get_load_balancer_security_groups()
        if load_balancer_security_groups is not None:
            if app_sg.inbound_rules is None:
                app_sg.inbound_rules = []
            if app_sg.depends_on is None:
                app_sg.depends_on = []

            for lb_sg in load_balancer_security_groups:
                app_sg.inbound_rules.append(
                    InboundRule(
                        description=f"Allow traffic from {lb_sg.name} to the {self.get_app_name()}",
                        port=self.container_port,
                        source_security_group_id=AwsReference(lb_sg.get_security_group_id),
                    )
                )
                app_sg.depends_on.append(lb_sg)

        # Allow traffic from inbound_security_groups
        if self.inbound_security_groups is not None:
            if app_sg.inbound_rules is None:
                app_sg.inbound_rules = []
            if app_sg.depends_on is None:
                app_sg.depends_on = []

            for inbound_sg in self.inbound_security_groups:
                app_sg.inbound_rules.append(
                    InboundRule(
                        description=f"Allow traffic from {inbound_sg.name} to the {self.get_app_name()}",
                        port=self.container_port,
                        source_security_group_id=AwsReference(inbound_sg.get_security_group_id),
                    )
                )

        # Allow traffic from inbound_security_group_ids
        if self.inbound_security_group_ids is not None:
            if app_sg.inbound_rules is None:
                app_sg.inbound_rules = []
            if app_sg.depends_on is None:
                app_sg.depends_on = []

            for inbound_sg_id in self.inbound_security_group_ids:
                app_sg.inbound_rules.append(
                    InboundRule(
                        description=f"Allow traffic from {inbound_sg_id} to the {self.get_app_name()}",
                        port=self.container_port,
                        source_security_group_id=inbound_sg_id,
                    )
                )

        return app_sg

    def get_security_groups(self) -> Optional[List["SecurityGroup"]]:
        from agno.aws.resource.ec2.security_group import SecurityGroup

        security_groups: Optional[List[SecurityGroup]] = self.security_groups
        if security_groups is None:
            # Create security group for the service
            if self.create_security_groups:
                security_groups = []
                app_security_group = self.security_group_definition()
                if app_security_group is not None:
                    security_groups.append(app_security_group)
        return security_groups

    def get_all_security_groups(self) -> Optional[List["SecurityGroup"]]:
        from agno.aws.resource.ec2.security_group import SecurityGroup

        security_groups: List[SecurityGroup] = []

        load_balancer_security_groups = self.get_load_balancer_security_groups()
        if load_balancer_security_groups is not None:
            for lb_sg in load_balancer_security_groups:
                if isinstance(lb_sg, SecurityGroup):
                    security_groups.append(lb_sg)

        service_security_groups = self.get_security_groups()
        if service_security_groups is not None:
            for sg in service_security_groups:
                if isinstance(sg, SecurityGroup):
                    security_groups.append(sg)

        return security_groups if len(security_groups) > 0 else None

    def ecs_cluster_definition(self) -> "EcsCluster":
        from agno.aws.resource.ecs.cluster import EcsCluster

        ecs_cluster = EcsCluster(
            name=f"{self.get_app_name()}-cluster",
            ecs_cluster_name=self.ecs_cluster_name or self.get_app_name(),
            capacity_providers=[self.ecs_launch_type],
        )
        if self.ecs_enable_service_connect:
            ecs_cluster.service_connect_namespace = self.ecs_service_connect_namespace
        return ecs_cluster

    def get_ecs_cluster(self) -> "EcsCluster":
        from agno.aws.resource.ecs.cluster import EcsCluster

        if self.ecs_cluster is None:
            if self.create_ecs_cluster:
                return self.ecs_cluster_definition()
            raise Exception("Please provide ECSCluster or set create_ecs_cluster to True")
        elif isinstance(self.ecs_cluster, EcsCluster):
            return self.ecs_cluster
        else:
            raise Exception(f"Invalid ECSCluster: {self.ecs_cluster} - Must be of type EcsCluster")

    def load_balancer_definition(self) -> "LoadBalancer":
        from agno.aws.resource.elb.load_balancer import LoadBalancer

        return LoadBalancer(
            name=f"{self.get_app_name()}-lb",
            subnets=self.subnets,
            security_groups=self.get_load_balancer_security_groups(),
            protocol="HTTPS" if self.load_balancer_enable_https else "HTTP",
        )

    def get_load_balancer(self) -> Optional["LoadBalancer"]:
        from agno.aws.resource.elb.load_balancer import LoadBalancer

        if self.load_balancer is None:
            if self.create_load_balancer:
                return self.load_balancer_definition()
            return None
        elif isinstance(self.load_balancer, LoadBalancer):
            return self.load_balancer
        else:
            raise Exception(f"Invalid LoadBalancer: {self.load_balancer} - Must be of type LoadBalancer")

    def target_group_definition(self) -> "TargetGroup":
        from agno.aws.resource.elb.target_group import TargetGroup

        return TargetGroup(
            name=f"{self.get_app_name()}-tg",
            port=self.target_group_port or self.container_port,
            protocol=self.target_group_protocol,
            subnets=self.subnets,
            target_type=self.target_group_type,
            health_check_protocol=self.health_check_protocol,
            health_check_port=self.health_check_port,
            health_check_enabled=self.health_check_enabled,
            health_check_path=self.health_check_path,
            health_check_interval_seconds=self.health_check_interval_seconds,
            health_check_timeout_seconds=self.health_check_timeout_seconds,
            healthy_threshold_count=self.healthy_threshold_count,
            unhealthy_threshold_count=self.unhealthy_threshold_count,
        )

    def get_target_group(self) -> Optional["TargetGroup"]:
        from agno.aws.resource.elb.target_group import TargetGroup

        if self.target_group is None:
            if self.create_target_group:
                return self.target_group_definition()
            return None
        elif isinstance(self.target_group, TargetGroup):
            return self.target_group
        else:
            raise Exception(f"Invalid TargetGroup: {self.target_group} - Must be of type TargetGroup")

    def listeners_definition(
        self, load_balancer: Optional["LoadBalancer"], target_group: Optional["TargetGroup"]
    ) -> List["Listener"]:
        from agno.aws.resource.elb.listener import Listener

        listener = Listener(
            name=f"{self.get_app_name()}-listener",
            load_balancer=load_balancer,
            target_group=target_group,
        )
        if self.load_balancer_certificate_arn is not None:
            listener.certificates = [{"CertificateArn": self.load_balancer_certificate_arn}]
        if self.load_balancer_certificate is not None:
            listener.acm_certificates = [self.load_balancer_certificate]

        listeners: List[Listener] = [listener]
        if self.load_balancer_enable_https:
            # Add a listener to redirect HTTP to HTTPS
            listeners.append(
                Listener(
                    name=f"{self.get_app_name()}-redirect-listener",
                    port=80,
                    protocol="HTTP",
                    load_balancer=load_balancer,
                    default_actions=[
                        {
                            "Type": "redirect",
                            "RedirectConfig": {
                                "Protocol": "HTTPS",
                                "Port": "443",
                                "StatusCode": "HTTP_301",
                                "Host": "#{host}",
                                "Path": "/#{path}",
                                "Query": "#{query}",
                            },
                        }
                    ],
                )
            )
        return listeners

    def get_listeners(
        self, load_balancer: Optional["LoadBalancer"], target_group: Optional["TargetGroup"]
    ) -> Optional[List["Listener"]]:
        from agno.aws.resource.elb.listener import Listener

        if self.listeners is None:
            if self.create_listeners:
                return self.listeners_definition(load_balancer, target_group)
            return None
        elif isinstance(self.listeners, list):
            for listener in self.listeners:
                if not isinstance(listener, Listener):
                    raise Exception(f"Invalid Listener: {listener} - Must be of type Listener")
            return self.listeners
        else:
            raise Exception(f"Invalid Listener: {self.listeners} - Must be of type List[Listener]")

    def get_container_command(self) -> Optional[List[str]]:
        if isinstance(self.command, str):
            return self.command.strip().split(" ")
        return self.command

    def get_ecs_container_port_mappings(self) -> List[Dict[str, Any]]:
        port_mapping: Dict[str, Any] = {"containerPort": self.container_port}
        # To enable service connect, we need to set the port name to the app name
        if self.ecs_enable_service_connect:
            port_mapping["name"] = self.get_app_name()
            if self.ecs_service_connect_protocol is not None:
                port_mapping["appProtocol"] = self.ecs_service_connect_protocol
        return [port_mapping]

    def get_ecs_container(self, container_context: ContainerContext, build_context: AwsBuildContext) -> "EcsContainer":
        from agno.aws.resource.ecs.container import EcsContainer

        # -*- Get Container Environment
        container_env: Dict[str, str] = self.get_container_env(
            container_context=container_context, build_context=build_context
        )

        # -*- Get Container Command
        container_cmd: Optional[List[str]] = self.get_container_command()
        if container_cmd:
            logger.debug("Command: {}".format(" ".join(container_cmd)))

        aws_region = build_context.aws_region or (
            self.workspace_settings.aws_region if self.workspace_settings else None
        )
        return EcsContainer(
            name=self.get_app_name(),
            image=self.get_image_str(),
            port_mappings=self.get_ecs_container_port_mappings(),
            command=container_cmd,
            essential=True,
            environment=[{"name": k, "value": v} for k, v in container_env.items()],
            log_configuration={
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": self.get_app_name(),
                    "awslogs-region": aws_region,
                    "awslogs-create-group": "true",
                    "awslogs-stream-prefix": self.get_app_name(),
                },
            },
            linux_parameters={"initProcessEnabled": True},
            env_from_secrets=self.aws_secrets,
        )

    def get_ecs_task_definition(self, ecs_container: "EcsContainer") -> "EcsTaskDefinition":
        from agno.aws.resource.ecs.task_definition import EcsTaskDefinition

        return EcsTaskDefinition(
            name=f"{self.get_app_name()}-td",
            family=self.get_app_name(),
            network_mode="awsvpc",
            cpu=self.ecs_task_cpu,
            memory=self.ecs_task_memory,
            containers=[ecs_container],
            requires_compatibilities=[self.ecs_launch_type],
            add_bedrock_access_to_task=self.ecs_bedrock_access,
            add_exec_access_to_task=self.ecs_exec_access,
            add_secret_access_to_ecs=self.ecs_secret_access,
            add_secret_access_to_task=self.ecs_secret_access,
            add_s3_access_to_task=self.ecs_s3_access,
        )

    def get_ecs_service(
        self,
        ecs_container: "EcsContainer",
        ecs_task_definition: "EcsTaskDefinition",
        ecs_cluster: "EcsCluster",
        target_group: Optional["TargetGroup"],
    ) -> Optional["EcsService"]:
        from agno.aws.resource.ecs.service import EcsService

        service_security_groups = self.get_security_groups()
        ecs_service = EcsService(
            name=f"{self.get_app_name()}-service",
            desired_count=self.ecs_service_count,
            launch_type=self.ecs_launch_type,
            cluster=ecs_cluster,
            task_definition=ecs_task_definition,
            target_group=target_group,
            target_container_name=ecs_container.name,
            target_container_port=self.container_port,
            subnets=self.subnets,
            security_groups=service_security_groups,
            assign_public_ip=self.assign_public_ip,
            # Force delete the service.
            force_delete=True,
            # Force a new deployment of the service on update.
            force_new_deployment=True,
            enable_execute_command=self.ecs_exec_access,
        )
        if self.ecs_enable_service_connect:
            # namespace is used from the cluster
            ecs_service.service_connect_configuration = {
                "enabled": True,
                "services": [
                    {
                        "portName": self.get_app_name(),
                        "clientAliases": [
                            {
                                "port": self.container_port,
                                "dnsName": self.get_app_name(),
                            }
                        ],
                    },
                ],
            }
        return ecs_service

    def build_resources(self, build_context: AwsBuildContext) -> List["AwsResource"]:
        from agno.aws.resource.base import AwsResource
        from agno.aws.resource.ec2.security_group import SecurityGroup
        from agno.aws.resource.ecs.cluster import EcsCluster
        from agno.aws.resource.ecs.container import EcsContainer
        from agno.aws.resource.ecs.service import EcsService
        from agno.aws.resource.ecs.task_definition import EcsTaskDefinition
        from agno.aws.resource.ecs.volume import EcsVolume
        from agno.aws.resource.elb.listener import Listener
        from agno.aws.resource.elb.load_balancer import LoadBalancer
        from agno.aws.resource.elb.target_group import TargetGroup
        from agno.docker.resource.image import DockerImage
        from agno.utils.defaults import get_default_volume_name

        logger.debug(f"------------ Building {self.get_app_name()} ------------")
        # -*- Get Container Context
        container_context: Optional[ContainerContext] = self.get_container_context()
        if container_context is None:
            raise Exception("Could not build ContainerContext")
        logger.debug(f"ContainerContext: {container_context.model_dump_json(indent=2)}")

        # -*- Get Security Groups
        security_groups: Optional[List[SecurityGroup]] = self.get_all_security_groups()

        # -*- Get ECS cluster
        ecs_cluster: EcsCluster = self.get_ecs_cluster()

        # -*- Get Load Balancer
        load_balancer: Optional[LoadBalancer] = self.get_load_balancer()

        # -*- Get Target Group
        target_group: Optional[TargetGroup] = self.get_target_group()
        # Point the target group to the nginx container port if:
        # - nginx is enabled
        # - user provided target_group is None
        # - user provided target_group_port is None
        if self.enable_nginx and self.target_group is None and self.target_group_port is None:
            if target_group is not None:
                target_group.port = self.nginx_container_port

        # -*- Get Listener
        listeners: Optional[List[Listener]] = self.get_listeners(load_balancer=load_balancer, target_group=target_group)

        # -*- Get ECSContainer
        ecs_container: EcsContainer = self.get_ecs_container(
            container_context=container_context, build_context=build_context
        )
        # -*- Add nginx container if nginx is enabled
        nginx_container: Optional[EcsContainer] = None
        nginx_shared_volume: Optional[EcsVolume] = None
        if self.enable_nginx and ecs_container is not None:
            nginx_container_name = f"{self.get_app_name()}-nginx"
            nginx_shared_volume = EcsVolume(name=get_default_volume_name(self.get_app_name()))
            nginx_image_str = f"{self.nginx_image_name}:{self.nginx_image_tag}"
            if self.nginx_image and isinstance(self.nginx_image, DockerImage):
                nginx_image_str = self.nginx_image.get_image_str()

            nginx_container = EcsContainer(
                name=nginx_container_name,
                image=nginx_image_str,
                essential=True,
                port_mappings=[{"containerPort": self.nginx_container_port}],
                environment=ecs_container.environment,
                log_configuration={
                    "logDriver": "awslogs",
                    "options": {
                        "awslogs-group": self.get_app_name(),
                        "awslogs-region": build_context.aws_region
                        or (self.workspace_settings.aws_region if self.workspace_settings else None),
                        "awslogs-create-group": "true",
                        "awslogs-stream-prefix": nginx_container_name,
                    },
                },
                mount_points=[
                    {
                        "sourceVolume": nginx_shared_volume.name,
                        "containerPath": container_context.workspace_root,
                    }
                ],
                linux_parameters=ecs_container.linux_parameters,
                env_from_secrets=ecs_container.env_from_secrets,
                save_output=ecs_container.save_output,
                output_dir=ecs_container.output_dir,
                skip_create=ecs_container.skip_create,
                skip_delete=ecs_container.skip_delete,
                wait_for_create=ecs_container.wait_for_create,
                wait_for_delete=ecs_container.wait_for_delete,
            )

            # Add shared volume to ecs_container
            ecs_container.mount_points = nginx_container.mount_points

        # -*- Get ECS Task Definition
        ecs_task_definition: EcsTaskDefinition = self.get_ecs_task_definition(ecs_container=ecs_container)
        # -*- Add nginx container to ecs_task_definition if nginx is enabled
        if self.enable_nginx:
            if ecs_task_definition is not None:
                if nginx_container is not None:
                    if ecs_task_definition.containers:
                        ecs_task_definition.containers.append(nginx_container)
                    else:
                        logger.error("While adding Nginx container, found TaskDefinition.containers to be None")
                else:
                    logger.error("While adding Nginx container, found nginx_container to be None")
                if nginx_shared_volume:
                    ecs_task_definition.volumes = [nginx_shared_volume]

        # -*- Get ECS Service
        ecs_service: Optional[EcsService] = self.get_ecs_service(
            ecs_cluster=ecs_cluster,
            ecs_task_definition=ecs_task_definition,
            target_group=target_group,
            ecs_container=ecs_container,
        )
        # -*- Add nginx container as target_container if nginx is enabled
        if self.enable_nginx:
            if ecs_service is not None:
                if nginx_container is not None:
                    ecs_service.target_container_name = nginx_container.name
                    ecs_service.target_container_port = self.nginx_container_port
                else:
                    logger.error("While adding Nginx container as target_container, found nginx_container to be None")

        # -*- List of AwsResources created by this App
        app_resources: List[AwsResource] = []
        if security_groups:
            app_resources.extend(security_groups)
        if load_balancer:
            app_resources.append(load_balancer)
        if target_group:
            app_resources.append(target_group)
        if listeners:
            app_resources.extend(listeners)
        if ecs_cluster:
            app_resources.append(ecs_cluster)
        if ecs_task_definition:
            app_resources.append(ecs_task_definition)
        if ecs_service:
            app_resources.append(ecs_service)

        logger.debug(f"------------ {self.get_app_name()} Built ------------")
        return app_resources
