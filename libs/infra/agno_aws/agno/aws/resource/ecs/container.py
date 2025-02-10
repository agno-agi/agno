from typing import Any, Dict, List, Optional, Union

from agno.aws.api_client import AwsApiClient
from agno.aws.resource.base import AwsResource
from agno.aws.resource.secret.manager import SecretsManager
from agno.aws.resource.secret.reader import read_secrets
from agno.utils.log import logger


class EcsContainer(AwsResource):
    """
    Reference:
    - https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ecs.html
    """

    resource_type: Optional[str] = "EcsContainer"
    service_name: str = "ecs"

    # The name of a container.
    # If you're linking multiple containers together in a task definition, the name of one container can be entered in
    # the links of another container to connect the containers.
    name: str
    # The image used to start a container.
    image: str
    # The private repository authentication credentials to use.
    repository_credentials: Optional[Dict[str, Any]] = None
    # The number of cpu units reserved for the container.
    cpu: Optional[int] = None
    # The amount (in MiB) of memory to present to the container.
    memory: Optional[int] = None
    # The soft limit (in MiB) of memory to reserve for the container.
    memory_reservation: Optional[int] = None
    # The links parameter allows containers to communicate with each other without the need for port mappings.
    links: Optional[List[str]] = None
    # The list of port mappings for the container. Port mappings allow containers to access ports on the host container
    # instance to send or receive traffic.
    port_mappings: Optional[List[Dict[str, Any]]] = None
    # If the essential parameter of a container is marked as true , and that container fails or stops for any reason,
    # all other containers that are part of the task are stopped. If the essential parameter of a container is marked
    # as false , its failure doesn't affect the rest of the containers in a task. If this parameter is omitted,
    # a container is assumed to be essential.
    essential: Optional[bool] = None
    # The entry point that's passed to the container.
    entry_point: Optional[List[str]] = None
    # The command that's passed to the container.
    command: Optional[List[str]] = None
    # The environment variables to pass to a container.
    environment: Optional[List[Dict[str, Any]]] = None
    # A list of files containing the environment variables to pass to a container.
    environment_files: Optional[List[Dict[str, Any]]] = None
    # Read environment variables from AWS Secrets.
    env_from_secrets: Optional[Union[SecretsManager, List[SecretsManager]]] = None
    # The mount points for data volumes in your container.
    mount_points: Optional[List[Dict[str, Any]]] = None
    # Data volumes to mount from another container.
    volumes_from: Optional[List[Dict[str, Any]]] = None
    # Linux-specific modifications that are applied to the container, such as Linux kernel capabilities.
    linux_parameters: Optional[Dict[str, Any]] = None
    # The secrets to pass to the container.
    secrets: Optional[List[Dict[str, Any]]] = None
    # The dependencies defined for container startup and shutdown.
    depends_on: Optional[List[Dict[str, Any]]] = None
    # Time duration (in seconds) to wait before giving up on resolving dependencies for a container.
    start_timeout: Optional[int] = None
    # Time duration (in seconds) to wait before the container is forcefully killed if it doesn't exit normally.
    stop_timeout: Optional[int] = None
    # The hostname to use for your container.
    hostname: Optional[str] = None
    # The user to use inside the container.
    user: Optional[str] = None
    # The working directory to run commands inside the container in.
    working_directory: Optional[str] = None
    # When this parameter is true, networking is disabled within the container.
    disable_networking: Optional[bool] = None
    # When this parameter is true, the container is given elevated privileges
    # on the host container instance (similar to the root user).
    privileged: Optional[bool] = None
    readonly_root_filesystem: Optional[bool] = None
    dns_servers: Optional[List[str]] = None
    dns_search_domains: Optional[List[str]] = None
    extra_hosts: Optional[List[Dict[str, Any]]] = None
    docker_security_options: Optional[List[str]] = None
    interactive: Optional[bool] = None
    pseudo_terminal: Optional[bool] = None
    docker_labels: Optional[Dict[str, Any]] = None
    ulimits: Optional[List[Dict[str, Any]]] = None
    log_configuration: Optional[Dict[str, Any]] = None
    health_check: Optional[Dict[str, Any]] = None
    system_controls: Optional[List[Dict[str, Any]]] = None
    resource_requirements: Optional[List[Dict[str, Any]]] = None
    firelens_configuration: Optional[Dict[str, Any]] = None

    def get_container_definition(self, aws_client: Optional[AwsApiClient] = None) -> Dict[str, Any]:
        container_definition: Dict[str, Any] = {}

        # Build container environment
        container_environment: List[Dict[str, Any]] = self.build_container_environment(aws_client=aws_client)
        if container_environment is not None:
            container_definition["environment"] = container_environment

        if self.name is not None:
            container_definition["name"] = self.name
        if self.image is not None:
            container_definition["image"] = self.image
        if self.repository_credentials is not None:
            container_definition["repositoryCredentials"] = self.repository_credentials
        if self.cpu is not None:
            container_definition["cpu"] = self.cpu
        if self.memory is not None:
            container_definition["memory"] = self.memory
        if self.memory_reservation is not None:
            container_definition["memoryReservation"] = self.memory_reservation
        if self.links is not None:
            container_definition["links"] = self.links
        if self.port_mappings is not None:
            container_definition["portMappings"] = self.port_mappings
        if self.essential is not None:
            container_definition["essential"] = self.essential
        if self.entry_point is not None:
            container_definition["entryPoint"] = self.entry_point
        if self.command is not None:
            container_definition["command"] = self.command
        if self.environment_files is not None:
            container_definition["environmentFiles"] = self.environment_files
        if self.mount_points is not None:
            container_definition["mountPoints"] = self.mount_points
        if self.volumes_from is not None:
            container_definition["volumesFrom"] = self.volumes_from
        if self.linux_parameters is not None:
            container_definition["linuxParameters"] = self.linux_parameters
        if self.secrets is not None:
            container_definition["secrets"] = self.secrets
        if self.depends_on is not None:
            container_definition["dependsOn"] = self.depends_on
        if self.start_timeout is not None:
            container_definition["startTimeout"] = self.start_timeout
        if self.stop_timeout is not None:
            container_definition["stopTimeout"] = self.stop_timeout
        if self.hostname is not None:
            container_definition["hostname"] = self.hostname
        if self.user is not None:
            container_definition["user"] = self.user
        if self.working_directory is not None:
            container_definition["workingDirectory"] = self.working_directory
        if self.disable_networking is not None:
            container_definition["disableNetworking"] = self.disable_networking
        if self.privileged is not None:
            container_definition["privileged"] = self.privileged
        if self.readonly_root_filesystem is not None:
            container_definition["readonlyRootFilesystem"] = self.readonly_root_filesystem
        if self.dns_servers is not None:
            container_definition["dnsServers"] = self.dns_servers
        if self.dns_search_domains is not None:
            container_definition["dnsSearchDomains"] = self.dns_search_domains
        if self.extra_hosts is not None:
            container_definition["extraHosts"] = self.extra_hosts
        if self.docker_security_options is not None:
            container_definition["dockerSecurityOptions"] = self.docker_security_options
        if self.interactive is not None:
            container_definition["interactive"] = self.interactive
        if self.pseudo_terminal is not None:
            container_definition["pseudoTerminal"] = self.pseudo_terminal
        if self.docker_labels is not None:
            container_definition["dockerLabels"] = self.docker_labels
        if self.ulimits is not None:
            container_definition["ulimits"] = self.ulimits
        if self.log_configuration is not None:
            container_definition["logConfiguration"] = self.log_configuration
        if self.health_check is not None:
            container_definition["healthCheck"] = self.health_check
        if self.system_controls is not None:
            container_definition["systemControls"] = self.system_controls
        if self.resource_requirements is not None:
            container_definition["resourceRequirements"] = self.resource_requirements
        if self.firelens_configuration is not None:
            container_definition["firelensConfiguration"] = self.firelens_configuration

        return container_definition

    def build_container_environment(self, aws_client: Optional[AwsApiClient] = None) -> List[Dict[str, Any]]:
        logger.debug("Building container environment")
        container_environment: List[Dict[str, Any]] = []
        if self.environment is not None:
            from agno.aws.resource.reference import AwsReference

            for env in self.environment:
                env_name = env.get("name", None)
                env_value = env.get("value", None)
                env_value_parsed = None
                if isinstance(env_value, AwsReference):
                    logger.debug(f"{env_name} is an AwsReference")
                    try:
                        env_value_parsed = env_value.get_reference(aws_client=aws_client)
                    except Exception as e:
                        logger.error(f"Error while parsing {env_name}: {e}")
                else:
                    env_value_parsed = env_value

                if env_value_parsed is not None:
                    try:
                        env_val_str = str(env_value_parsed)
                        container_environment.append({"name": env_name, "value": env_val_str})
                    except Exception as e:
                        logger.error(f"Error while converting {env_value} to str: {e}")

        if self.env_from_secrets is not None:
            secrets: Dict[str, Any] = read_secrets(self.env_from_secrets, aws_client=aws_client)
            for secret_name, secret_value in secrets.items():
                try:
                    secret_value = str(secret_value)
                    container_environment.append({"name": secret_name, "value": secret_value})
                except Exception as e:
                    logger.error(f"Error while converting {secret_value} to str: {e}")
        return container_environment
