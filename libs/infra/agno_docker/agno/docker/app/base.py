from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from agno.docker.context import DockerBuildContext
from agno.infra.app import InfraApp
from agno.infra.context import ContainerContext
from agno.utils.log import logger

if TYPE_CHECKING:
    from agno.docker.resource.base import DockerResource


class DockerApp(InfraApp):
    # -*- Workspace Configuration
    # Path to the workspace directory inside the container
    workspace_dir_container_path: str = "/app"
    # Mount the workspace directory from host machine to the container
    mount_workspace: bool = False

    # -*- App Volume
    # Create a volume for container storage
    create_volume: bool = False
    # If volume_dir is provided, mount this directory RELATIVE to the workspace_root
    # from the host machine to the volume_container_path
    volume_dir: Optional[str] = None
    # Otherwise, mount a volume named volume_name to the container
    # If volume_name is not provided, use {app-name}-volume
    volume_name: Optional[str] = None
    # Path to mount the volume inside the container
    volume_container_path: str = "/mnt/app"

    # -*- Resources Volume
    # Mount a read-only directory from host machine to the container
    mount_resources: bool = False
    # Resources directory relative to the workspace_root
    resources_dir: str = "workspace/resources"
    # Path to mount the resources_dir
    resources_dir_container_path: str = "/mnt/resources"

    # -*- Agno Volume
    # Mount ~/.config/ag directory from host machine to the container
    mount_agno_config: bool = True

    # -*- Container Configuration
    container_name: Optional[str] = None
    container_labels: Optional[Dict[str, str]] = None
    # Run container in the background and return a Container object
    container_detach: bool = True
    # Enable auto-removal of the container on daemon side when the container’s process exits
    container_auto_remove: bool = True
    # Remove the container when it has finished running. Default: True
    container_remove: bool = True
    # Username or UID to run commands as inside the container
    container_user: Optional[Union[str, int]] = None
    # Keep STDIN open even if not attached
    container_stdin_open: bool = True
    # Return logs from STDOUT when container_detach=False
    container_stdout: Optional[bool] = True
    # Return logs from STDERR when container_detach=False
    container_stderr: Optional[bool] = True
    container_tty: bool = True
    # Specify a test to perform to check that the container is healthy
    container_healthcheck: Optional[Dict[str, Any]] = None
    # Optional hostname for the container
    container_hostname: Optional[str] = None
    # Platform in the format os[/arch[/variant]]
    container_platform: Optional[str] = None
    # Path to the working directory
    container_working_dir: Optional[str] = None
    # Restart the container when it exits. Configured as a dictionary with keys:
    # Name: One of on-failure, or always.
    # MaximumRetryCount: Number of times to restart the container on failure.
    # For example: {"Name": "on-failure", "MaximumRetryCount": 5}
    container_restart_policy: Optional[Dict[str, Any]] = None
    # Add volumes to DockerContainer
    # container_volumes is a dictionary which adds the volumes to mount
    # inside the container. The key is either the host path or a volume name,
    # and the value is a dictionary with 2 keys:
    #   bind - The path to mount the volume inside the container
    #   mode - Either rw to mount the volume read/write, or ro to mount it read-only.
    # For example:
    # {
    #   '/home/user1/': {'bind': '/mnt/vol2', 'mode': 'rw'},
    #   '/var/www': {'bind': '/mnt/vol1', 'mode': 'ro'}
    # }
    container_volumes: Optional[Dict[str, dict]] = None
    # Add ports to DockerContainer
    # The keys of the dictionary are the ports to bind inside the container,
    # either as an integer or a string in the form port/protocol, where the protocol is either tcp, udp.
    # The values of the dictionary are the corresponding ports to open on the host, which can be either:
    #   - The port number, as an integer.
    #     For example, {'2222/tcp': 3333} will expose port 2222 inside the container as port 3333 on the host.
    #   - None, to assign a random host port. For example, {'2222/tcp': None}.
    #   - A tuple of (address, port) if you want to specify the host interface.
    #     For example, {'1111/tcp': ('127.0.0.1', 1111)}.
    #   - A list of integers, if you want to bind multiple host ports to a single container port.
    #     For example, {'1111/tcp': [1234, 4567]}.
    container_ports: Optional[Dict[str, Any]] = None

    def get_container_name(self) -> str:
        return self.container_name or self.get_app_name()

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

    def get_container_env(self, container_context: ContainerContext) -> Dict[str, str]:
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
                "MOUNT_RESOURCES": str(self.mount_resources),
                "MOUNT_WORKSPACE": str(self.mount_workspace),
                "PRINT_ENV_ON_LOAD": str(self.print_env_on_load),
                "RESOURCES_DIR_CONTAINER_PATH": str(self.resources_dir_container_path),
                AGNO_RUNTIME_ENV_VAR: "docker",
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
                if self.mount_resources and self.resources_dir_container_path is not None:
                    python_path = "{}:{}".format(python_path, self.resources_dir_container_path)
                if self.add_python_paths is not None:
                    python_path = "{}:{}".format(python_path, ":".join(self.add_python_paths))
            if python_path is not None:
                container_env[PYTHONPATH_ENV_VAR] = python_path

        # Set aws region and profile
        self.set_aws_env_vars(env_dict=container_env)

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
            container_env.update({k: str(v) for k, v in self.env_vars.items() if v is not None})

        # logger.debug("Container Environment: {}".format(container_env))
        return container_env

    def get_container_volumes(self, container_context: ContainerContext) -> Dict[str, dict]:
        from agno.utils.defaults import get_default_volume_name

        if self.workspace_root is None:
            logger.error("Invalid workspace_root")
            return {}

        # container_volumes is a dictionary which configures the volumes to mount
        # inside the container. The key is either the host path or a volume name,
        # and the value is a dictionary with 2 keys:
        #   bind - The path to mount the volume inside the container
        #   mode - Either rw to mount the volume read/write, or ro to mount it read-only.
        # For example:
        # {
        #   '/home/user1/': {'bind': '/mnt/vol2', 'mode': 'rw'},
        #   '/var/www': {'bind': '/mnt/vol1', 'mode': 'ro'}
        # }
        container_volumes = self.container_volumes or {}

        # Create Workspace Volume
        if self.mount_workspace:
            workspace_root_in_container = container_context.workspace_root
            workspace_root_on_host = str(self.workspace_root)
            logger.debug(f"Mounting: {workspace_root_on_host}")
            logger.debug(f"      to: {workspace_root_in_container}")
            container_volumes[workspace_root_on_host] = {
                "bind": workspace_root_in_container,
                "mode": "rw",
            }

        # Create App Volume
        if self.create_volume:
            volume_host = self.volume_name or get_default_volume_name(self.get_app_name())
            if self.volume_dir is not None:
                volume_host = str(self.workspace_root.joinpath(self.volume_dir))
            logger.debug(f"Mounting: {volume_host}")
            logger.debug(f"      to: {self.volume_container_path}")
            container_volumes[volume_host] = {
                "bind": self.volume_container_path,
                "mode": "rw",
            }

        # Create Resources Volume
        if self.mount_resources:
            resources_dir_path = str(self.workspace_root.joinpath(self.resources_dir))
            logger.debug(f"Mounting: {resources_dir_path}")
            logger.debug(f"      to: {self.resources_dir_container_path}")
            container_volumes[resources_dir_path] = {
                "bind": self.resources_dir_container_path,
                "mode": "ro",
            }

        # Add ~/.config/ag as a volume
        if self.mount_agno_config:
            agno_config_host_path = str(Path.home().joinpath(".config/ag"))
            agno_config_container_path = f"{self.workspace_dir_container_path}/.config/ag"
            logger.debug(f"Mounting: {agno_config_host_path}")
            logger.debug(f"      to: {agno_config_container_path}")
            container_volumes[agno_config_host_path] = {
                "bind": agno_config_container_path,
                "mode": "ro",
            }

        return container_volumes

    def get_container_ports(self) -> Dict[str, int]:
        # container_ports is a dictionary which configures the ports to bind
        # inside the container. The key is the port to bind inside the container
        #   either as an integer or a string in the form port/protocol
        # and the value is the corresponding port to open on the host.
        # For example:
        #   {'2222/tcp': 3333} will expose port 2222 inside the container as port 3333 on the host.
        container_ports: Dict[str, int] = self.container_ports or {}

        if self.open_port:
            _container_port = self.container_port or self.port_number
            _host_port = self.host_port or self.port_number
            container_ports[str(_container_port)] = _host_port

        return container_ports

    def get_container_command(self) -> Optional[List[str]]:
        if isinstance(self.command, str):
            return self.command.strip().split(" ")
        return self.command

    def build_resources(self, build_context: DockerBuildContext) -> List["DockerResource"]:
        from agno.docker.resource.base import DockerResource
        from agno.docker.resource.container import DockerContainer
        from agno.docker.resource.network import DockerNetwork

        logger.debug(f"------------ Building {self.get_app_name()} ------------")
        # -*- Get Container Context
        container_context: Optional[ContainerContext] = self.get_container_context()
        if container_context is None:
            raise Exception("Could not build ContainerContext")
        logger.debug(f"ContainerContext: {container_context.model_dump_json(indent=2)}")

        # -*- Get Container Environment
        container_env: Dict[str, str] = self.get_container_env(container_context=container_context)

        # -*- Get Container Volumes
        container_volumes = self.get_container_volumes(container_context=container_context)

        # -*- Get Container Ports
        container_ports: Dict[str, int] = self.get_container_ports()

        # -*- Get Container Command
        container_cmd: Optional[List[str]] = self.get_container_command()
        if container_cmd:
            logger.debug("Command: {}".format(" ".join(container_cmd)))

        # -*- Build the DockerContainer for this App
        docker_container = DockerContainer(
            name=self.get_container_name(),
            image=self.get_image_str(),
            entrypoint=self.entrypoint,
            command=" ".join(container_cmd) if container_cmd is not None else None,
            detach=self.container_detach,
            auto_remove=self.container_auto_remove if not self.debug_mode else False,
            remove=self.container_remove if not self.debug_mode else False,
            healthcheck=self.container_healthcheck,
            hostname=self.container_hostname,
            labels=self.container_labels,
            environment=container_env,
            network=build_context.network,
            platform=self.container_platform,
            ports=container_ports if len(container_ports) > 0 else None,
            restart_policy=self.container_restart_policy,
            stdin_open=self.container_stdin_open,
            stderr=self.container_stderr,
            stdout=self.container_stdout,
            tty=self.container_tty,
            user=self.container_user,
            volumes=container_volumes if len(container_volumes) > 0 else None,
            working_dir=self.container_working_dir,
            use_cache=self.use_cache,
        )

        # -*- List of DockerResources created by this App
        app_resources: List[DockerResource] = []
        if self.image:
            app_resources.append(self.image)
        app_resources.extend(
            [
                DockerNetwork(name=build_context.network),
                docker_container,
            ]
        )

        logger.debug(f"------------ {self.get_app_name()} Built ------------")
        return app_resources

    def get_infra_resources(self) -> Optional[Any]:
        from agno.docker.resources import DockerResources

        return DockerResources(
            name=self.get_app_name(),
            apps=[self],
        )
