import json
import os
import sys
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import logger

if sys.version_info >= (3, 12):
    # Apply more comprehensive monkey patch for Python 3.12 compatibility
    try:
        import inspect

        from docker import auth

        # Create a more comprehensive patched version that ignores any unknown parameters
        original_load_config = auth.load_config

        def patched_load_config(*args, **kwargs):
            # Get the original function's parameters
            try:
                sig = inspect.signature(original_load_config)
                # Filter out any kwargs that aren't in the signature
                valid_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
                return original_load_config(*args, **valid_kwargs)
            except Exception as e:
                logger.warning(f"Error in patched_load_config: {e}")
                return {}

        # Replace the original function with our patched version
        auth.load_config = patched_load_config

        # Add the missing get_config_header function
        if not hasattr(auth, "get_config_header"):

            def get_config_header(client, registry=None):
                """
                Replacement for missing get_config_header function.
                Returns empty auth headers to avoid authentication errors.
                """
                return {}

            # Add the function to the auth module
            auth.get_config_header = get_config_header
            logger.info("Added missing get_config_header function for Docker auth compatibility")

        logger.info("Applied comprehensive compatibility patch for Docker client on Python 3.12")
    except Exception as e:
        logger.warning(f"Failed to apply Docker client compatibility patch: {e}")

try:
    import docker
    from docker.errors import DockerException, ImageNotFound
except ImportError:
    raise ImportError("The `docker` package is not installed. Please install it via `pip install docker`.")


class DockerTools(Toolkit):
    def __init__(
        self,
        enable_container_management: bool = True,
        enable_image_management: bool = True,
        enable_volume_management: bool = False,
        enable_network_management: bool = False,
        **kwargs,
    ):
        self._check_docker_availability()

        try:
            os.environ["DOCKER_CONFIG"] = ""

            if hasattr(self, "socket_path"):
                socket_url = f"unix://{self.socket_path}"
                self.client = docker.DockerClient(base_url=socket_url)
            else:
                self.client = docker.DockerClient()

            self.client.ping()
            logger.info("Successfully connected to Docker daemon")
        except Exception as e:
            logger.error(f"Error connecting to Docker: {e}")

        tools: List[Any] = []
        if enable_container_management:
            tools.extend(
                [
                    self.list_containers,
                    self.start_container,
                    self.stop_container,
                    self.remove_container,
                    self.get_container_logs,
                    self.inspect_container,
                    self.run_container,
                    self.exec_in_container,
                ]
            )
        if enable_image_management:
            tools.extend(
                [
                    self.list_images,
                    self.pull_image,
                    self.remove_image,
                    self.build_image,
                    self.tag_image,
                    self.inspect_image,
                ]
            )
        if enable_volume_management:
            tools.extend([self.list_volumes, self.create_volume, self.remove_volume, self.inspect_volume])
        if enable_network_management:
            tools.extend(
                [
                    self.list_networks,
                    self.create_network,
                    self.remove_network,
                    self.inspect_network,
                    self.connect_container_to_network,
                    self.disconnect_container_from_network,
                ]
            )

        super().__init__(name="docker_tools", tools=tools, **kwargs)

    def _check_docker_availability(self):
        """Check if Docker socket exists and is accessible."""
        # Common Docker socket paths
        socket_paths = [
            # Linux/macOS
            "/var/run/docker.sock",
            # macOS Docker Desktop
            os.path.expanduser("~/.docker/run/docker.sock"),
            # macOS newer versions
            os.path.join(os.path.expanduser("~"), ".docker", "desktop", "docker.sock"),
            # macOS alternative
            os.path.expanduser("~/Library/Containers/com.docker.docker/Data/docker.sock"),
            # Windows
            os.path.join("\\", "\\", ".", "pipe", "docker_engine"),
        ]

        # Check if any socket exists
        socket_exists = any(os.path.exists(path) for path in socket_paths)
        if not socket_exists:
            logger.error("Docker socket not found. Is Docker installed and running?")
            raise ValueError(
                "Docker socket not found. Please make sure Docker is installed and running.\n"
                "On macOS: Start Docker Desktop application.\n"
                "On Linux: Run 'sudo systemctl start docker'."
            )

        # Find the first available socket path
        for path in socket_paths:
            if os.path.exists(path):
                logger.info(f"Found Docker socket at {path}")
                self.socket_path = path
                return

    def list_containers(self, all: bool = False) -> str:
        """
        List Docker containers.

        Args:
            all (bool): If True, show all containers (default shows just running).

        Returns:
            str: A JSON string containing the list of containers.
        """
        try:
            containers = self.client.containers.list(all=all)
            container_list = []

            for container in containers:
                # Handle cases where container image might not have tags
                image_info = container.image.tags[0] if container.image.tags else container.image.id

                container_list.append(
                    {
                        "id": container.id,
                        "name": container.name,
                        "image": image_info,
                        "status": container.status,
                        "created": container.attrs.get("Created"),
                        "ports": container.ports,
                        "labels": container.labels,
                    }
                )

            return json.dumps(container_list, indent=2)
        except DockerException as e:
            error_msg = f"Error listing containers: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def start_container(self, container_id: str) -> str:
        """
        Start a Docker container.

        Args:
            container_id (str): The ID or name of the container to start.

        Returns:
            str: A success message or error message.
        """
        try:
            container = self.client.containers.get(container_id)
            container.start()
            return f"Container {container_id} started successfully"
        except DockerException as e:
            error_msg = f"Error starting container: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def stop_container(self, container_id: str, timeout: int = 10) -> str:
        """
        Stop a Docker container.

        Args:
            container_id (str): The ID or name of the container to stop.
            timeout (int): Timeout in seconds to wait for container to stop.

        Returns:
            str: A success message or error message.
        """
        try:
            container = self.client.containers.get(container_id)
            container.stop(timeout=timeout)
            return f"Container {container_id} stopped successfully"
        except DockerException as e:
            error_msg = f"Error stopping container: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def remove_container(self, container_id: str, force: bool = False, volumes: bool = False) -> str:
        """
        Remove a Docker container.

        Args:
            container_id (str): The ID or name of the container to remove.
            force (bool): If True, force the removal of a running container.
            volumes (bool): If True, remove anonymous volumes associated with the container.

        Returns:
            str: A success message or error message.
        """
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=force, v=volumes)
            return f"Container {container_id} removed successfully"
        except DockerException as e:
            error_msg = f"Error removing container: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def get_container_logs(self, container_id: str, tail: int = 100, stream: bool = False) -> str:
        """
        Get logs from a Docker container.

        Args:
            container_id (str): The ID or name of the container.
            tail (int): Number of lines to show from the end of the logs.
            stream (bool): If True, return a generator that yields log lines.

        Returns:
            str: The container logs or an error message.
        """
        try:
            container = self.client.containers.get(container_id)
            logs = container.logs(tail=tail, stream=stream)
            if isinstance(logs, bytes):
                return logs.decode("utf-8", errors="replace")
            # If streaming, we can't meaningfully return this as a string
            if stream:
                return "Logs are being streamed. This function returns data when stream=False."
            return "No logs found"
        except DockerException as e:
            error_msg = f"Error getting container logs: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def inspect_container(self, container_id: str) -> str:
        """
        Inspect a Docker container.

        Args:
            container_id (str): The ID or name of the container.

        Returns:
            str: A JSON string containing detailed information about the container.
        """
        try:
            container = self.client.containers.get(container_id)
            return json.dumps(container.attrs, indent=2)
        except DockerException as e:
            error_msg = f"Error inspecting container: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def run_container(
        self,
        image: str,
        command: Optional[str] = None,
        name: Optional[str] = None,
        detach: bool = True,
        ports: Optional[Dict[str, Union[str, int]]] = None,  # Updated type hint
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        environment: Optional[Dict[str, str]] = None,
        network: Optional[str] = None,
    ) -> str:
        """
        Run a Docker container.

        Args:
            image (str): The image to run.
            command (str, optional): The command to run in the container.
            name (str, optional): A name for the container.
            detach (bool): Run container in the background.
            ports (dict, optional): Port mappings {'container_port/protocol': host_port}.
            volumes (dict, optional): Volume mappings.
            environment (dict, optional): Environment variables.
            network (str, optional): Network to connect the container to.

        Returns:
            str: Container ID or error message.
        """
        try:
            # Fix port mapping: convert integer values to strings
            if ports:
                fixed_ports = {}
                for container_port, host_port in ports.items():
                    if isinstance(host_port, int):
                        host_port = str(host_port)
                    fixed_ports[container_port] = host_port
            else:
                fixed_ports = None

            container = self.client.containers.run(
                image=image,
                command=command,
                name=name,
                detach=detach,
                ports=fixed_ports,  # Use the fixed ports
                volumes=volumes,
                environment=environment,
                network=network,
            )
            return f"Container started with ID: {container.id}"
        except DockerException as e:
            error_msg = f"Error running container: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def exec_in_container(self, container_id: str, command: str) -> str:
        """
        Execute a command in a running container.

        Args:
            container_id (str): The ID or name of the container.
            command (str): The command to execute.

        Returns:
            str: Command output or error message.
        """
        try:
            container = self.client.containers.get(container_id)
            exit_code, output = container.exec_run(command)
            if isinstance(output, bytes):
                output_str = output.decode("utf-8", errors="replace")
            else:
                output_str = str(output)

            if exit_code == 0:
                return output_str
            else:
                return f"Command failed with exit code {exit_code}: {output_str}"
        except DockerException as e:
            error_msg = f"Error executing command in container: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def list_images(self) -> str:
        """
        List Docker images.

        Returns:
            str: A JSON string containing the list of images.
        """
        try:
            images = self.client.images.list()
            image_list = []

            for image in images:
                image_list.append(
                    {
                        "id": image.id,
                        "tags": image.tags,
                        "created": image.attrs.get("Created"),
                        "size": image.attrs.get("Size"),
                        "labels": image.labels,
                    }
                )

            return json.dumps(image_list, indent=2)
        except DockerException as e:
            error_msg = f"Error listing images: {str(e)}"
            logger.error(error_msg)
            return error_msg  # type: ignore

    def pull_image(self, image_name: str, tag: str = "latest") -> str:
        """
        Pull a Docker image.

        Args:
            image_name (str): The name of the image to pull.
            tag (str): The tag to pull.

        Returns:
            str: A success message or error message.
        """
        try:
            logger.info(f"Starting to pull image {image_name}:{tag}")
            for line in self.client.api.pull(image_name, tag=tag, stream=True, decode=True):
                if "progress" in line:
                    logger.info(f"Pulling {image_name}:{tag} - {line.get('progress', '')}")
                elif "status" in line:
                    logger.info(f"Pull status: {line.get('status', '')}")

            logger.info(f"Successfully pulled image {image_name}:{tag}")
            return f"Image {image_name}:{tag} pulled successfully"
        except Exception as e:
            error_msg = f"Error pulling image: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def remove_image(self, image_id: str, force: bool = False) -> str:
        """
        Remove a Docker image.

        Args:
            image_id (str): The ID or name of the image to remove.
            force (bool): If True, force removal of the image.

        Returns:
            str: A success message or error message.
        """
        try:
            self.client.images.remove(image_id, force=force)
            return f"Image {image_id} removed successfully"
        except ImageNotFound:
            return f"Image {image_id} not found"
        except DockerException as e:
            error_msg = f"Error removing image: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def build_image(self, path: str, tag: str, dockerfile: str = "Dockerfile", rm: bool = True) -> str:
        """
        Build a Docker image from a Dockerfile.

        Args:
            path (str): Path to the directory containing the Dockerfile.
            tag (str): Tag to apply to the built image.
            dockerfile (str): Name of the Dockerfile.
            rm (bool): Remove intermediate containers.

        Returns:
            str: A success message or error message.
        """
        try:
            image, logs = self.client.images.build(path=path, tag=tag, dockerfile=dockerfile, rm=rm)
            return f"Image built successfully with ID: {image.id}"
        except DockerException as e:
            error_msg = f"Error building image: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def tag_image(self, image_id: str, repository: str, tag: Optional[str] = None) -> str:
        """
        Tag a Docker image.

        Args:
            image_id (str): The ID or name of the image to tag.
            repository (str): The repository to tag in.
            tag (str, optional): The tag name.

        Returns:
            str: A success message or error message.
        """
        try:
            image = self.client.images.get(image_id)
            image.tag(repository, tag=tag)
            return f"Image {image_id} tagged as {repository}:{tag or 'latest'}"
        except DockerException as e:
            error_msg = f"Error tagging image: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def inspect_image(self, image_id: str) -> str:
        """
        Inspect a Docker image.

        Args:
            image_id (str): The ID or name of the image.

        Returns:
            str: A JSON string containing detailed information about the image.
        """
        try:
            image = self.client.images.get(image_id)
            return json.dumps(image.attrs, indent=2)
        except DockerException as e:
            error_msg = f"Error inspecting image: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def list_volumes(self) -> str:
        """
        List Docker volumes.

        Returns:
            str: A JSON string containing the list of volumes.
        """
        try:
            volumes = self.client.volumes.list()
            volume_list = []

            for volume in volumes:
                volume_list.append(
                    {
                        "name": volume.name,
                        "driver": volume.attrs.get("Driver"),
                        "mountpoint": volume.attrs.get("Mountpoint"),
                        "created": volume.attrs.get("CreatedAt"),
                        "labels": volume.attrs.get("Labels", {}),
                    }
                )

            return json.dumps(volume_list, indent=2)
        except DockerException as e:
            error_msg = f"Error listing volumes: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def create_volume(self, volume_name: str, driver: str = "local", labels: Optional[Dict[str, str]] = None) -> str:
        """
        Create a Docker volume.

        Args:
            volume_name (str): The name of the volume to create.
            driver (str): The volume driver to use.
            labels (dict, optional): Labels to apply to the volume.

        Returns:
            str: A success message or error message.
        """
        try:
            self.client.volumes.create(name=volume_name, driver=driver, labels=labels)
            return f"Volume {volume_name} created successfully"
        except DockerException as e:
            error_msg = f"Error creating volume: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def remove_volume(self, volume_name: str, force: bool = False) -> str:
        """
        Remove a Docker volume.

        Args:
            volume_name (str): The name of the volume to remove.
            force (bool): Force removal of the volume.

        Returns:
            str: A success message or error message.
        """
        try:
            volume = self.client.volumes.get(volume_name)
            volume.remove(force=force)
            return f"Volume {volume_name} removed successfully"
        except DockerException as e:
            error_msg = f"Error removing volume: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def inspect_volume(self, volume_name: str) -> str:
        """
        Inspect a Docker volume.

        Args:
            volume_name (str): The name of the volume.

        Returns:
            str: A JSON string containing detailed information about the volume.
        """
        try:
            volume = self.client.volumes.get(volume_name)
            return json.dumps(volume.attrs, indent=2)
        except DockerException as e:
            error_msg = f"Error inspecting volume: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def list_networks(self) -> str:
        """
        List Docker networks.

        Returns:
            str: A JSON string containing the list of networks.
        """
        try:
            networks = self.client.networks.list()
            network_list = []

            for network in networks:
                network_list.append(
                    {
                        "id": network.id,
                        "name": network.name,
                        "driver": network.attrs.get("Driver"),
                        "scope": network.attrs.get("Scope"),
                        "created": network.attrs.get("Created"),
                        "internal": network.attrs.get("Internal", False),
                        "containers": list(network.attrs.get("Containers", {}).keys()),
                    }
                )

            return json.dumps(network_list, indent=2)
        except DockerException as e:
            error_msg = f"Error listing networks: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def create_network(
        self, network_name: str, driver: str = "bridge", internal: bool = False, labels: Optional[Dict[str, str]] = None
    ) -> str:
        """
        Create a Docker network.

        Args:
            network_name (str): The name of the network to create.
            driver (str): The network driver to use.
            internal (bool): If True, create an internal network.
            labels (dict, optional): Labels to apply to the network.

        Returns:
            str: A success message or error message.
        """
        try:
            network = self.client.networks.create(name=network_name, driver=driver, internal=internal, labels=labels)
            return f"Network {network_name} created successfully with ID: {network.id}"
        except DockerException as e:
            error_msg = f"Error creating network: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def remove_network(self, network_name: str) -> str:
        """
        Remove a Docker network.

        Args:
            network_name (str): The name of the network to remove.

        Returns:
            str: A success message or error message.
        """
        try:
            network = self.client.networks.get(network_name)
            network.remove()
            return f"Network {network_name} removed successfully"
        except DockerException as e:
            error_msg = f"Error removing network: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def inspect_network(self, network_name: str) -> str:
        """
        Inspect a Docker network.

        Args:
            network_name (str): The name of the network.

        Returns:
            str: A JSON string containing detailed information about the network.
        """
        try:
            network = self.client.networks.get(network_name)
            return json.dumps(network.attrs, indent=2)
        except DockerException as e:
            error_msg = f"Error inspecting network: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def connect_container_to_network(self, container_id: str, network_name: str) -> str:
        """
        Connect a container to a network.

        Args:
            container_id (str): The ID or name of the container.
            network_name (str): The name of the network.

        Returns:
            str: A success message or error message.
        """
        try:
            network = self.client.networks.get(network_name)
            network.connect(container_id)
            return f"Container {container_id} connected to network {network_name}"
        except DockerException as e:
            error_msg = f"Error connecting container to network: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def disconnect_container_from_network(self, container_id: str, network_name: str) -> str:
        """
        Disconnect a container from a network.

        Args:
            container_id (str): The ID or name of the container.
            network_name (str): The name of the network.

        Returns:
            str: A success message or error message.
        """
        try:
            network = self.client.networks.get(network_name)
            network.disconnect(container_id)
            return f"Container {container_id} disconnected from network {network_name}"
        except DockerException as e:
            error_msg = f"Error disconnecting container from network: {str(e)}"
            logger.error(error_msg)
            return error_msg
