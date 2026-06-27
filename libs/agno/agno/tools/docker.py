import json
import os
import sys
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_error, log_warning, logger

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
                log_warning(f"Error in patched_load_config: {str(e)}")
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
        log_warning(f"Failed to apply Docker client compatibility patch: {str(e)}")

try:
    import docker
    from docker.errors import DockerException, ImageNotFound
except ImportError:
    raise ImportError("The `docker` package is not installed. Please install it via `pip install docker`.")


class DockerTools(Toolkit):
    """Docker toolkit.

    Security notes (hardened build):

    * The process-wide ``DOCKER_CONFIG=""`` wipe has been removed; it
      invalidated registry credentials for unrelated code running in
      the same Python process.
    * Privileged and destructive operations (``run_container``,
      ``exec_in_container``, ``build_image``, ``pull_image``,
      ``remove_*``, volume / network create and connect) are not
      registered as LLM-callable tools unless
      ``enable_privileged_ops=True``.
    * Inspection operations (``list_volumes``, ``inspect_volume``,
      ``list_networks``, ``inspect_network``) disclose internal
      volume mount paths and network topology to the LLM. They are
      not registered by default; set ``enable_inspection_ops=True``
      when you explicitly need them. The minimal container/image
      listing tools remain registered because they are already
      bounded by ``container_allowlist`` / ``image_allowlist``.
    * When privileged ops are enabled, :meth:`run_container`
      additionally requires explicit allowlists for the parameters
      that reach the Docker API unchanged. ``volumes``, ``network``,
      and ``environment`` arguments are refused by default; only the
      host paths, network names, and environment keys configured on
      the toolkit may be passed through. The following host paths
      are **blanket denied** regardless of allowlist contents:
      ``/`` (host root), ``/var/run/docker.sock`` (docker socket —
      root-on-host escalation), ``/proc``, ``/sys``, ``/dev``,
      ``/etc``, ``/root``, ``/boot``. ``network="host"`` is also
      blanket denied.
    * Optional ``image_allowlist`` and ``container_allowlist`` sets
      restrict which targets the LLM may act on. An image specifier
      without a tag matches the bare repository name; ``@sha256``
      suffixes are stripped before comparison.

    Args:
        enable_privileged_ops: Register mutating Docker tools.
        enable_inspection_ops: Register the four volume / network
            inspection tools. Off by default to avoid disclosing
            host topology to the LLM.
        image_allowlist: Iterable of allowed image repositories or
            fully qualified ``repo:tag`` specifiers.
        container_allowlist: Iterable of allowed container IDs or
            names.
        allowed_bind_mounts: Iterable of host paths that may appear
            on the left-hand side of a ``volumes`` mapping passed to
            :meth:`run_container`. When None (default), any non-None
            ``volumes`` argument is refused.
        allowed_networks: Iterable of network names that may be
            passed as ``network`` to :meth:`run_container`. When
            None, any non-None ``network`` is refused.
        allowed_env_keys: Iterable of environment variable names that
            may appear in ``environment``. When None, any non-None
            ``environment`` dict is refused.
    """

    # Paths that MUST NOT be bind-mounted from the host into a
    # container under any circumstances. Mounting any of these gives
    # the LLM root-on-host or comparable escalation. This list is
    # enforced even when the operator configures
    # ``allowed_bind_mounts`` — it is a floor, not a ceiling.
    _BLANKET_DENIED_BINDS: FrozenSet[str] = frozenset(
        {
            "/",
            "/var/run/docker.sock",
            "/var/run",
            "/proc",
            "/sys",
            "/dev",
            "/etc",
            "/root",
            "/boot",
            "/usr",
            "/bin",
            "/sbin",
            "/lib",
            "/lib64",
        }
    )

    def __init__(
        self,
        enable_privileged_ops: bool = False,
        enable_inspection_ops: bool = False,
        image_allowlist: Optional[Iterable[str]] = None,
        container_allowlist: Optional[Iterable[str]] = None,
        allowed_bind_mounts: Optional[Iterable[str]] = None,
        allowed_networks: Optional[Iterable[str]] = None,
        allowed_env_keys: Optional[Iterable[str]] = None,
        **kwargs,
    ):
        self._check_docker_availability()

        try:
            if hasattr(self, "socket_path"):
                socket_url = f"unix://{self.socket_path}"
                self.client = docker.DockerClient(base_url=socket_url)
            else:
                self.client = docker.DockerClient()

            self.client.ping()
            logger.info("Successfully connected to Docker daemon")
        except Exception:
            logger.exception("Error connecting to Docker")

        self._enable_privileged_ops: bool = bool(enable_privileged_ops)
        self._enable_inspection_ops: bool = bool(enable_inspection_ops)
        self._image_allowlist: Optional[FrozenSet[str]] = (
            frozenset(i.strip() for i in image_allowlist) if image_allowlist else None
        )
        self._container_allowlist: Optional[FrozenSet[str]] = (
            frozenset(c.strip() for c in container_allowlist) if container_allowlist else None
        )
        self._allowed_bind_mounts: Optional[FrozenSet[str]] = (
            frozenset(b.rstrip("/") or "/" for b in allowed_bind_mounts) if allowed_bind_mounts else None
        )
        self._allowed_networks: Optional[FrozenSet[str]] = (
            frozenset(n.strip() for n in allowed_networks) if allowed_networks else None
        )
        self._allowed_env_keys: Optional[FrozenSet[str]] = (
            frozenset(k.strip() for k in allowed_env_keys) if allowed_env_keys else None
        )

        tools: List[Any] = [
            self.list_containers,
            self.get_container_logs,
            self.inspect_container,
            self.list_images,
            self.inspect_image,
        ]
        if self._enable_inspection_ops:
            tools.extend(
                [
                    self.list_volumes,
                    self.inspect_volume,
                    self.list_networks,
                    self.inspect_network,
                ]
            )

        if self._enable_privileged_ops:
            logger.warning(
                "DockerTools: privileged operations ENABLED; the LLM "
                "can mutate containers, images, volumes, and networks."
            )
            tools.extend(
                [
                    self.start_container,
                    self.stop_container,
                    self.remove_container,
                    self.run_container,
                    self.exec_in_container,
                    self.pull_image,
                    self.remove_image,
                    self.build_image,
                    self.tag_image,
                    self.create_volume,
                    self.remove_volume,
                    self.create_network,
                    self.remove_network,
                    self.connect_container_to_network,
                    self.disconnect_container_from_network,
                ]
            )

        super().__init__(name="docker_tools", tools=tools, **kwargs)

    def _assert_bind_mount_allowed(self, host_path: str) -> Optional[str]:
        """Return a reason string if ``host_path`` cannot be bind-mounted.

        Enforces two rules:

        * Blanket-denied paths (``/``, ``/var/run/docker.sock``,
          ``/proc``, ``/etc``, etc.) are refused even when the
          operator configures an allowlist.
        * Otherwise the path (normalised by stripping trailing
          slashes) must appear in ``allowed_bind_mounts``. When that
          allowlist is unset, any bind-mount is refused.
        """
        if not isinstance(host_path, str) or not host_path:
            return "Bind-mount host path must be a non-empty string."
        normalised = host_path.rstrip("/") or "/"
        if normalised in self._BLANKET_DENIED_BINDS:
            return f"Bind-mount of '{host_path}' is blanket-denied by the hardened build."
        if self._allowed_bind_mounts is None:
            return "Bind-mounts are refused unless allowed_bind_mounts is configured."
        if normalised not in self._allowed_bind_mounts:
            return f"Bind-mount host path '{host_path}' is not in allowed_bind_mounts."
        return None

    def _assert_volumes_allowed(self, volumes: Optional[Dict[str, Dict[str, str]]]) -> Optional[str]:
        """Validate every entry in a ``docker-py`` ``volumes`` mapping."""
        if volumes is None:
            return None
        if not isinstance(volumes, dict):
            return "volumes must be a dict when provided."
        for host_path in volumes.keys():
            reason = self._assert_bind_mount_allowed(host_path)
            if reason:
                return reason
        return None

    def _assert_network_allowed(self, network: Optional[str]) -> Optional[str]:
        """Refuse ``network='host'`` and enforce the network allowlist."""
        if network is None:
            return None
        if not isinstance(network, str) or not network:
            return "network must be a non-empty string when provided."
        if network.strip().lower() == "host":
            return "network='host' is blanket-denied by the hardened build."
        if self._allowed_networks is None:
            return "A network name is refused unless allowed_networks is configured."
        if network not in self._allowed_networks:
            return f"Network '{network}' is not in allowed_networks."
        return None

    def _assert_environment_allowed(self, environment: Optional[Dict[str, str]]) -> Optional[str]:
        """Enforce the environment-variable key allowlist."""
        if environment is None:
            return None
        if not isinstance(environment, dict):
            return "environment must be a dict when provided."
        if self._allowed_env_keys is None:
            return "environment variables are refused unless allowed_env_keys is configured."
        for key in environment.keys():
            if key not in self._allowed_env_keys:
                return f"Environment variable '{key}' is not in allowed_env_keys."
        return None

    def _assert_image_allowed(self, image: str) -> Optional[str]:
        """Return a reason string if ``image`` is outside the allowlist."""
        if self._image_allowlist is None:
            return None
        base = image.split("@", 1)[0]
        repo = base.split(":", 1)[0]
        if base in self._image_allowlist or image in self._image_allowlist or repo in self._image_allowlist:
            return None
        return f"Image '{image}' is not in the configured allowlist."

    def _assert_container_allowed(self, container_id: str) -> Optional[str]:
        """Return a reason string if ``container_id`` is outside the allowlist."""
        if self._container_allowlist is None:
            return None
        if container_id in self._container_allowlist:
            return None
        try:
            c = self.client.containers.get(container_id)
            if c.name in self._container_allowlist:
                return None
        except Exception:
            pass
        return f"Container '{container_id}' is not in the configured allowlist."

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
            log_error("Docker socket not found. Is Docker installed and running?")
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
        err = self._assert_container_allowed(container_id)
        if err:
            log_error(err)
            return f"Error: {err}"
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=force, v=volumes)
            return f"Container {container_id} removed successfully"
        except DockerException as e:
            error_msg = f"Error removing container: {str(e)}"
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            volumes (dict, optional): Volume mappings. By default refused;
                requires ``allowed_bind_mounts`` at construction time,
                and a set of host paths is blanket-denied even then
                (``/``, ``/var/run/docker.sock``, ``/proc``, etc.).
            environment (dict, optional): Environment variables. By
                default refused; requires ``allowed_env_keys`` at
                construction time.
            network (str, optional): Network to connect the container
                to. By default refused; requires ``allowed_networks``
                at construction time. ``"host"`` is blanket-denied.

        Returns:
            str: Container ID or error message.
        """
        for reason in (
            self._assert_image_allowed(image),
            self._assert_volumes_allowed(volumes),
            self._assert_network_allowed(network),
            self._assert_environment_allowed(environment),
        ):
            if reason:
                log_error(reason)
                return f"Error: {reason}"
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
            log_error(error_msg)
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
        err = self._assert_container_allowed(container_id)
        if err:
            log_error(err)
            return f"Error: {err}"
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
            log_error(error_msg)
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
            log_error(error_msg)
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
        err = self._assert_image_allowed(f"{image_name}:{tag}")
        if err:
            log_error(err)
            return f"Error: {err}"
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
            log_error(error_msg)
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
        err = self._assert_image_allowed(image_id)
        if err:
            log_error(err)
            return f"Error: {err}"
        try:
            self.client.images.remove(image_id, force=force)
            return f"Image {image_id} removed successfully"
        except ImageNotFound:
            return f"Image {image_id} not found"
        except DockerException as e:
            error_msg = f"Error removing image: {str(e)}"
            log_error(error_msg)
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
        err = self._assert_image_allowed(tag)
        if err:
            log_error(err)
            return f"Error: {err}"
        try:
            image, logs = self.client.images.build(path=path, tag=tag, dockerfile=dockerfile, rm=rm)
            return f"Image built successfully with ID: {image.id}"
        except DockerException as e:
            error_msg = f"Error building image: {str(e)}"
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
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
            log_error(error_msg)
            return error_msg
