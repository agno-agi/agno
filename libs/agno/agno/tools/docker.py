import json
from typing import Dict, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import docker
    from docker.errors import DockerException, ImageNotFound
except ImportError:
    raise ImportError("`docker` not installed. Please install using `pip install docker`")


class DockerTools(Toolkit):
    def __init__(
        self,
        enable_container_management: bool = True,
        enable_image_management: bool = True,
        enable_volume_management: bool = True,
        enable_network_management: bool = True,
    ):
        """Initialize Docker tools."""
        super().__init__(name="docker")

        # Initialize Docker client
        try:
            self.client = docker.from_env()
            # Test connection
            self.client.ping()
        except DockerException:
            logger.error("Docker is not installed or not accessible")
            raise ValueError("Docker is not installed or not accessible")

        # Register tools based on enabled features
        if enable_container_management:
            self.register(self.list_containers)
            self.register(self.start_container)
            self.register(self.stop_container)
            self.register(self.remove_container)
            self.register(self.get_container_logs)
            self.register(self.inspect_container)
            self.register(self.run_container)
            self.register(self.exec_in_container)
        
        if enable_image_management:
            self.register(self.list_images)
            self.register(self.pull_image)
            self.register(self.remove_image)
            self.register(self.build_image)
            self.register(self.tag_image)
            self.register(self.inspect_image)
        
        if enable_volume_management:
            self.register(self.list_volumes)
            self.register(self.create_volume)
            self.register(self.remove_volume)
            self.register(self.inspect_volume)
        
        if enable_network_management:
            self.register(self.list_networks)
            self.register(self.create_network)
            self.register(self.remove_network)
            self.register(self.inspect_network)
            self.register(self.connect_container_to_network)
            self.register(self.disconnect_container_from_network)

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
                container_list.append({
                    "id": container.id,
                    "name": container.name,
                    "image": container.image.tags[0] if container.image.tags else container.image.id,
                    "status": container.status,
                    "created": container.attrs.get("Created"),
                    "ports": container.ports,
                    "labels": container.labels
                })
            
            return json.dumps(container_list, indent=2)
        except DockerException as e:
            logger.error(f"Error listing containers: {e}")
            return f"Error listing containers: {str(e)}"

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
            logger.error(f"Error starting container: {e}")
            return f"Error starting container: {str(e)}"

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
            logger.error(f"Error stopping container: {e}")
            return f"Error stopping container: {str(e)}"

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
            logger.error(f"Error removing container: {e}")
            return f"Error removing container: {str(e)}"

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
            logs = container.logs(tail=tail, stream=stream).decode('utf-8')
            return logs
        except DockerException as e:
            logger.error(f"Error getting container logs: {e}")
            return f"Error getting container logs: {str(e)}"

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
            logger.error(f"Error inspecting container: {e}")
            return f"Error inspecting container: {str(e)}"

    def run_container(
        self, 
        image: str, 
        command: Optional[str] = None, 
        name: Optional[str] = None,
        detach: bool = True,
        ports: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        environment: Optional[Dict[str, str]] = None,
        network: Optional[str] = None
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
            container = self.client.containers.run(
                image=image,
                command=command,
                name=name,
                detach=detach,
                ports=ports,
                volumes=volumes,
                environment=environment,
                network=network
            )
            return f"Container started with ID: {container.id}"
        except DockerException as e:
            logger.error(f"Error running container: {e}")
            return f"Error running container: {str(e)}"

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
            if exit_code == 0:
                return output.decode('utf-8')
            else:
                return f"Command failed with exit code {exit_code}: {output.decode('utf-8')}"
        except DockerException as e:
            logger.error(f"Error executing command in container: {e}")
            return f"Error executing command in container: {str(e)}"

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
                image_list.append({
                    "id": image.id,
                    "tags": image.tags,
                    "created": image.attrs.get("Created"),
                    "size": image.attrs.get("Size"),
                    "labels": image.labels
                })
            
            return json.dumps(image_list, indent=2)
        except DockerException as e:
            logger.error(f"Error listing images: {e}")
            return f"Error listing images: {str(e)}"

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
            self.client.images.pull(image_name, tag=tag)
            return f"Image {image_name}:{tag} pulled successfully"
        except DockerException as e:
            logger.error(f"Error pulling image: {e}")
            return f"Error pulling image: {str(e)}"

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
            logger.error(f"Error removing image: {e}")
            return f"Error removing image: {str(e)}"

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
            image, logs = self.client.images.build(
                path=path,
                tag=tag,
                dockerfile=dockerfile,
                rm=rm
            )
            return f"Image built successfully with ID: {image.id}"
        except DockerException as e:
            logger.error(f"Error building image: {e}")
            return f"Error building image: {str(e)}"

    def tag_image(self, image_id: str, repository: str, tag: str = None) -> str:
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
            logger.error(f"Error tagging image: {e}")
            return f"Error tagging image: {str(e)}"

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
            logger.error(f"Error inspecting image: {e}")
            return f"Error inspecting image: {str(e)}"

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
                volume_list.append({
                    "name": volume.name,
                    "driver": volume.attrs.get("Driver"),
                    "mountpoint": volume.attrs.get("Mountpoint"),
                    "created": volume.attrs.get("CreatedAt"),
                    "labels": volume.attrs.get("Labels", {})
                })
            
            return json.dumps(volume_list, indent=2)
        except DockerException as e:
            logger.error(f"Error listing volumes: {e}")
            return f"Error listing volumes: {str(e)}"

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
            volume = self.client.volumes.create(
                name=volume_name,
                driver=driver,
                labels=labels
            )
            return f"Volume {volume_name} created successfully"
        except DockerException as e:
            logger.error(f"Error creating volume: {e}")
            return f"Error creating volume: {str(e)}"

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
            logger.error(f"Error removing volume: {e}")
            return f"Error removing volume: {str(e)}"

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
            logger.error(f"Error inspecting volume: {e}")
            return f"Error inspecting volume: {str(e)}"

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
                network_list.append({
                    "id": network.id,
                    "name": network.name,
                    "driver": network.attrs.get("Driver"),
                    "scope": network.attrs.get("Scope"),
                    "created": network.attrs.get("Created"),
                    "internal": network.attrs.get("Internal", False),
                    "containers": list(network.attrs.get("Containers", {}).keys())
                })
            
            return json.dumps(network_list, indent=2)
        except DockerException as e:
            logger.error(f"Error listing networks: {e}")
            return f"Error listing networks: {str(e)}"

    def create_network(
        self, 
        network_name: str, 
        driver: str = "bridge", 
        internal: bool = False,
        labels: Optional[Dict[str, str]] = None
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
            network = self.client.networks.create(
                name=network_name,
                driver=driver,
                internal=internal,
                labels=labels
            )
            return f"Network {network_name} created successfully with ID: {network.id}"
        except DockerException as e:
            logger.error(f"Error creating network: {e}")
            return f"Error creating network: {str(e)}"

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
            logger.error(f"Error removing network: {e}")
            return f"Error removing network: {str(e)}"

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
            logger.error(f"Error inspecting network: {e}")
            return f"Error inspecting network: {str(e)}"

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
            logger.error(f"Error connecting container to network: {e}")
            return f"Error connecting container to network: {str(e)}"

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
            logger.error(f"Error disconnecting container from network: {e}")
            return f"Error disconnecting container from network: {str(e)}"
