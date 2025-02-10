from typing import Any, Dict, List, Optional

from agno.cli.console import console, print_info
from agno.docker.api_client import DockerApiClient
from agno.docker.resource.base import DockerResource
from agno.utils.log import logger


class DockerImage(DockerResource):
    resource_type: str = "Image"

    # Docker image name, usually as repo/image
    name: str
    # Docker image tag
    tag: Optional[str] = None

    # Path to the directory containing the Dockerfile
    path: Optional[str] = None
    # Path to the Dockerfile within the build context
    dockerfile: Optional[str] = None

    # Print the build log
    print_build_log: bool = True
    # Push the image to the registry. Similar to the docker push command.
    push_image: bool = False
    print_push_output: bool = False
    # Use buildx for building images
    use_buildx: bool = True

    # Remove intermediate containers.
    # The docker build command defaults to --rm=true,
    # The docker api kept the old default of False to preserve backward compatibility
    rm: Optional[bool] = True
    # Always remove intermediate containers, even after unsuccessful builds
    forcerm: Optional[bool] = None
    # HTTP timeout
    timeout: Optional[int] = None
    # Downloads any updates to the FROM image in Dockerfiles
    pull: Optional[bool] = None
    # Skips docker cache when set to True
    # i.e. rebuilds all layes of the image
    skip_docker_cache: Optional[bool] = None
    # A dictionary of build arguments
    buildargs: Optional[Dict[str, Any]] = None
    # A dictionary of limits applied to each container created by the build process. Valid keys:
    # memory (int): set memory limit for build
    # memswap (int): Total memory (memory + swap), -1 to disable swap
    # cpushares (int): CPU shares (relative weight)
    # cpusetcpus (str): CPUs in which to allow execution, e.g. "0-3", "0,1"
    container_limits: Optional[Dict[str, Any]] = None
    # Size of /dev/shm in bytes. The size must be greater than 0. If omitted the system uses 64MB
    shmsize: Optional[int] = None
    # A dictionary of labels to set on the image
    labels: Optional[Dict[str, Any]] = None
    # A list of images used for build cache resolution
    cache_from: Optional[List[Any]] = None
    # Name of the build-stage to build in a multi-stage Dockerfile
    target: Optional[str] = None
    # networking mode for the run commands during build
    network_mode: Optional[str] = None
    # Squash the resulting images layers into a single layer.
    squash: Optional[bool] = None
    # Extra hosts to add to /etc/hosts in building containers, as a mapping of hostname to IP address.
    extra_hosts: Optional[Dict[str, Any]] = None
    # Platform in the format os[/arch[/variant]].
    platform: Optional[str] = None
    # List of platforms to use for build, uses buildx_image if multi-platform build is enabled.
    platforms: Optional[List[str]] = None
    # Isolation technology used during build. Default: None.
    isolation: Optional[str] = None
    # If True, and if the docker client configuration file (~/.docker/config.json by default)
    # contains a proxy configuration, the corresponding environment variables
    # will be set in the container being built.
    use_config_proxy: Optional[bool] = None

    # Set skip_delete=True so that the image is not deleted when the `ag ws down` command is run
    skip_delete: bool = True
    image_build_id: Optional[str] = None

    # Set use_cache to False so image is always built
    use_cache: bool = False

    def get_image_str(self) -> str:
        if self.tag:
            return f"{self.name}:{self.tag}"
        return f"{self.name}:latest"

    def get_resource_name(self) -> str:
        return self.get_image_str()

    def buildx(self, docker_client: Optional[DockerApiClient] = None) -> Optional[Any]:
        """Builds the image using buildx

        Args:
            docker_client: The DockerApiClient for the current cluster

        Options: https://docs.docker.com/engine/reference/commandline/buildx_build/#options
        """
        try:
            import subprocess

            tag = self.get_image_str()
            nocache = self.skip_docker_cache or self.force
            pull = self.pull or self.force

            print_info(f"Building image: {tag}")
            if self.path is not None:
                print_info(f"\t  path: {self.path}")
            if self.dockerfile is not None:
                print_info(f"    dockerfile: {self.dockerfile}")
            if self.platforms is not None:
                print_info(f"     platforms: {self.platforms}")
            logger.debug(f"nocache: {nocache}")
            logger.debug(f"pull: {pull}")

            command = ["docker", "buildx", "build"]

            # Add tag
            command.extend(["--tag", tag])

            # Add dockerfile option, if set
            if self.dockerfile is not None:
                command.extend(["--file", self.dockerfile])

            # Add build arguments
            if self.buildargs:
                for key, value in self.buildargs.items():
                    command.extend(["--build-arg", f"{key}={value}"])

            # Add no-cache option, if set
            if nocache:
                command.append("--no-cache")

            if not self.rm:
                command.append("--rm=false")

            if self.platforms:
                command.append("--platform={}".format(",".join(self.platforms)))

            if self.pull:
                command.append("--pull")

            if self.push_image:
                command.append("--push")
            else:
                command.append("--load")

            # Add path
            if self.path is not None:
                command.append(self.path)

            # Run the command
            logger.debug("Running command: {}".format(" ".join(command)))
            result = subprocess.run(command)

            # Handling output and errors
            if result.returncode == 0:
                print_info("Docker image built successfully.")
                return True
                # _docker_client = docker_client or self.get_docker_client()
                # return self._read(docker_client=_docker_client)
            else:
                logger.error("Error in building Docker image:")
                return False
        except Exception as e:
            logger.error(e)
            return None

    def build_image(self, docker_client: DockerApiClient) -> Optional[Any]:
        if self.platforms is not None or self.use_buildx:
            logger.debug("Using buildx for multi-platform build")
            return self.buildx(docker_client=docker_client)

        from docker import DockerClient
        from docker.errors import APIError, BuildError
        from rich import box
        from rich.live import Live
        from rich.table import Table

        print_info(f"Building image: {self.get_image_str()}")
        nocache = self.skip_docker_cache or self.force
        pull = self.pull or self.force
        if self.path is not None:
            print_info(f"\t  path: {self.path}")
        if self.dockerfile is not None:
            print_info(f"    dockerfile: {self.dockerfile}")
        logger.debug(f"platform: {self.platform}")
        logger.debug(f"nocache: {nocache}")
        logger.debug(f"pull: {pull}")

        last_status = None
        last_build_log = None
        build_log_output: List[Any] = []
        build_step_progress: List[str] = []
        build_log_to_show_on_error: List[str] = []
        try:
            _api_client: DockerClient = docker_client.api_client
            build_stream = _api_client.api.build(
                tag=self.get_image_str(),
                path=self.path,
                dockerfile=self.dockerfile,
                nocache=nocache,
                rm=self.rm,
                forcerm=self.forcerm,
                timeout=self.timeout,
                pull=pull,
                buildargs=self.buildargs,
                container_limits=self.container_limits,
                shmsize=self.shmsize,
                labels=self.labels,
                cache_from=self.cache_from,
                target=self.target,
                network_mode=self.network_mode,
                squash=self.squash,
                extra_hosts=self.extra_hosts,
                platform=self.platform,
                isolation=self.isolation,
                use_config_proxy=self.use_config_proxy,
                decode=True,
            )

            with Live(transient=True, console=console) as live_log:
                for build_log in build_stream:
                    if build_log != last_build_log:
                        last_build_log = build_log
                        build_log_output.append(build_log)

                    build_status: str = build_log.get("status")
                    if build_status is not None:
                        _status = build_status.lower()
                        if _status in (
                            "waiting",
                            "downloading",
                            "extracting",
                            "verifying checksum",
                            "pulling fs layer",
                        ):
                            continue
                        if build_status != last_status:
                            logger.debug(build_status)
                            last_status = build_status

                    if build_log.get("error", None) is not None:
                        live_log.stop()
                        logger.error(build_log_output[-50:])
                        logger.error(build_log["error"])
                        logger.error(f"Image build failed: {self.get_image_str()}")
                        return None

                    stream = build_log.get("stream", None)
                    if stream is None or stream == "\n":
                        continue
                    stream = stream.strip()

                    if "Step" in stream and self.print_build_log:
                        build_step_progress = []
                        print_info(stream)
                    else:
                        build_step_progress.append(stream)
                        if len(build_step_progress) > 10:
                            build_step_progress.pop(0)

                    build_log_to_show_on_error.append(stream)
                    if len(build_log_to_show_on_error) > 50:
                        build_log_to_show_on_error.pop(0)

                    if "error" in stream.lower():
                        print(stream)
                        live_log.stop()

                        # Render error table
                        error_table = Table(show_edge=False, show_header=False, show_lines=False)
                        for line in build_log_to_show_on_error:
                            error_table.add_row(line, style="dim")
                        error_table.add_row(stream, style="bold red")
                        console.print(error_table)
                        return None
                    if build_log.get("aux", None) is not None:
                        logger.debug("build_log['aux'] :{}".format(build_log["aux"]))
                        self.image_build_id = build_log.get("aux", {}).get("ID")

                    # Render table
                    table = Table(show_edge=False, show_header=False, show_lines=False)
                    for line in build_step_progress:
                        table.add_row(line, style="dim")
                    live_log.update(table)

            if self.push_image:
                print_info(f"Pushing {self.get_image_str()}")
                with Live(transient=True, console=console) as live_log:
                    push_status = {}
                    last_push_progress = None
                    for push_output in _api_client.images.push(
                        repository=self.name,
                        tag=self.tag,
                        stream=True,
                        decode=True,
                    ):
                        _id = push_output.get("id", None)
                        _status = push_output.get("status", None)
                        _progress = push_output.get("progress", None)
                        if _id is not None and _status is not None:
                            push_status[_id] = {
                                "status": _status,
                                "progress": _progress,
                            }

                        if push_output.get("error", None) is not None:
                            logger.error(push_output["error"])
                            logger.error(f"Push failed for {self.get_image_str()}")
                            logger.error("If you are using a private registry, make sure you are logged in")
                            return None

                        if self.print_push_output and push_output.get("status", None) in (
                            "Pushing",
                            "Pushed",
                        ):
                            current_progress = push_output.get("progress", None)
                            if current_progress != last_push_progress:
                                print_info(current_progress)
                                last_push_progress = current_progress
                        if push_output.get("aux", {}).get("Size", 0) > 0:
                            print_info(f"Push complete: {push_output.get('aux', {})}")

                        # Render table
                        table = Table(box=box.ASCII2)
                        table.add_column("Layer", justify="center")
                        table.add_column("Status", justify="center")
                        table.add_column("Progress", justify="center")
                        for layer, layer_status in push_status.items():
                            table.add_row(
                                layer,
                                layer_status["status"],
                                layer_status["progress"],
                                style="dim",
                            )
                        live_log.update(table)

            return self._read(docker_client)
        except TypeError as type_error:
            logger.error(type_error)
        except BuildError as build_error:
            logger.error(build_error)
        except APIError as api_err:
            logger.error(api_err)
        except Exception as e:
            logger.error(e)
        return None

    def _create(self, docker_client: DockerApiClient) -> bool:
        """Creates the image

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        logger.debug("Creating: {}".format(self.get_resource_name()))
        try:
            image_object = self.build_image(docker_client)
            if image_object is not None:
                return True
            return False
            # if image_object is not None and isinstance(image_object, Image):
            #     logger.debug("Image built: {}".format(image_object))
            #     self.active_resource = image_object
            #     return True
        except Exception as e:
            logger.exception(e)
            logger.error("Error while creating image: {}".format(e))
            raise

    def _read(self, docker_client: DockerApiClient) -> Any:
        """Returns an Image object if available

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        from docker import DockerClient
        from docker.errors import ImageNotFound, NotFound
        from docker.models.images import Image

        logger.debug("Reading: {}".format(self.get_image_str()))
        try:
            _api_client: DockerClient = docker_client.api_client
            image_object: Optional[List[Image]] = _api_client.images.get(name=self.get_image_str())
            if image_object is not None and isinstance(image_object, Image):
                logger.debug("Image found: {}".format(image_object))
                self.active_resource = image_object
                return image_object
        except (NotFound, ImageNotFound):
            logger.debug(f"Image {self.tag} not found")

        return None

    def _update(self, docker_client: DockerApiClient) -> bool:
        """Updates the Image

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        logger.debug("Updating: {}".format(self.get_resource_name()))
        return self._create(docker_client=docker_client)

    def _delete(self, docker_client: DockerApiClient) -> bool:
        """Deletes the Image

        Args:
            docker_client: The DockerApiClient for the current cluster
        """
        from docker import DockerClient
        from docker.models.images import Image

        logger.debug("Deleting: {}".format(self.get_resource_name()))
        image_object: Optional[Image] = self._read(docker_client)
        # Return True if there is no image to delete
        if image_object is None:
            logger.debug("No image to delete")
            return True

        # Delete Image
        try:
            self.active_resource = None
            logger.debug("Deleting image: {}".format(self.tag))
            _api_client: DockerClient = docker_client.api_client
            _api_client.images.remove(image=self.tag, force=True)
            return True
        except Exception as e:
            logger.exception("Error while deleting image: {}".format(e))

        return False

    def create(self, docker_client: DockerApiClient) -> bool:
        # If self.force then always create container
        if not self.force:
            # If use_cache is True and image is active then return True
            if self.use_cache and self.is_active(docker_client=docker_client):
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} already exists")
                return True

        resource_created = self._create(docker_client=docker_client)
        if resource_created:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} created")
            return True
        logger.error(f"Failed to create {self.get_resource_type()}: {self.get_resource_name()}")
        return False
