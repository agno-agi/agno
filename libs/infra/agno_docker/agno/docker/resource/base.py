from typing import Any, Dict, Optional

from agno.cli.console import print_info
from agno.docker.api_client import DockerApiClient
from agno.infra.resource import InfraResource
from agno.utils.log import logger


class DockerResource(InfraResource):
    """Base class for Docker Resources."""

    # Fields received from the DockerApiClient
    id: Optional[str] = None
    short_id: Optional[str] = None
    attrs: Optional[Dict[str, Any]] = None

    # Pull latest image before create/update
    pull: Optional[bool] = None

    docker_client: Optional[DockerApiClient] = None

    @staticmethod
    def get_from_cluster(docker_client: DockerApiClient) -> Any:
        """Gets all resources of this type from the Docker cluster"""
        logger.warning("@get_from_cluster method not defined")
        return None

    def get_docker_client(self) -> DockerApiClient:
        if self.docker_client is not None:
            return self.docker_client
        self.docker_client = DockerApiClient()
        return self.docker_client

    def _read(self, docker_client: DockerApiClient) -> Any:
        logger.warning(f"@_read method not defined for {self.get_resource_name()}")
        return True

    def read(self, docker_client: DockerApiClient) -> Any:
        """Reads the resource from the docker cluster"""
        # Step 1: Use cached value if available
        if self.use_cache and self.active_resource is not None:
            return self.active_resource

        # Step 2: Skip resource creation if skip_read = True
        if self.skip_read:
            print_info(f"Skipping read: {self.get_resource_name()}")
            return True

        # Step 3: Read resource
        client: DockerApiClient = docker_client or self.get_docker_client()
        return self._read(client)

    def is_active(self, docker_client: DockerApiClient) -> bool:
        """Returns True if the active is active on the docker cluster"""
        self.active_resource = self._read(docker_client=docker_client)
        return True if self.active_resource is not None else False

    def _create(self, docker_client: DockerApiClient) -> bool:
        logger.warning(f"@_create method not defined for {self.get_resource_name()}")
        return True

    def create(self, docker_client: DockerApiClient) -> bool:
        """Creates the resource on the docker cluster"""

        # Step 1: Skip resource creation if skip_create = True
        if self.skip_create:
            print_info(f"Skipping create: {self.get_resource_name()}")
            return True

        # Step 2: Check if resource is active and use_cache = True
        client: DockerApiClient = docker_client or self.get_docker_client()
        if self.use_cache and self.is_active(client):
            self.resource_created = True
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} already exists")
        # Step 3: Create the resource
        else:
            self.resource_created = self._create(client)
            if self.resource_created:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} created")

        # Step 4: Run post create steps
        if self.resource_created:
            if self.save_output:
                self.save_output_file()
            logger.debug(f"Running post-create for {self.get_resource_type()}: {self.get_resource_name()}")
            return self.post_create(client)
        logger.error(f"Failed to create {self.get_resource_type()}: {self.get_resource_name()}")
        return self.resource_created

    def post_create(self, docker_client: DockerApiClient) -> bool:
        return True

    def _update(self, docker_client: DockerApiClient) -> bool:
        logger.warning(f"@_update method not defined for {self.get_resource_name()}")
        return True

    def update(self, docker_client: DockerApiClient) -> bool:
        """Updates the resource on the docker cluster"""

        # Step 1: Skip resource update if skip_update = True
        if self.skip_update:
            print_info(f"Skipping update: {self.get_resource_name()}")
            return True

        # Step 2: Update the resource
        client: DockerApiClient = docker_client or self.get_docker_client()
        if self.is_active(client):
            self.resource_updated = self._update(client)
        else:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} not active, creating...")
            return self.create(client)

        # Step 3: Run post update steps
        if self.resource_updated:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} updated")
            if self.save_output:
                self.save_output_file()
            logger.debug(f"Running post-update for {self.get_resource_type()}: {self.get_resource_name()}")
            return self.post_update(client)
        logger.error(f"Failed to update {self.get_resource_type()}: {self.get_resource_name()}")
        return self.resource_updated

    def post_update(self, docker_client: DockerApiClient) -> bool:
        return True

    def _delete(self, docker_client: DockerApiClient) -> bool:
        logger.warning(f"@_delete method not defined for {self.get_resource_name()}")
        return False

    def delete(self, docker_client: DockerApiClient) -> bool:
        """Deletes the resource from the docker cluster"""

        # Step 1: Skip resource deletion if skip_delete = True
        if self.skip_delete:
            print_info(f"Skipping delete: {self.get_resource_name()}")
            return True

        # Step 2: Delete the resource
        client: DockerApiClient = docker_client or self.get_docker_client()
        if self.is_active(client):
            self.resource_deleted = self._delete(client)
        else:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} does not exist")
            return True

        # Step 3: Run post delete steps
        if self.resource_deleted:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} deleted")
            if self.save_output:
                self.delete_output_file()
            logger.debug(f"Running post-delete for {self.get_resource_type()}: {self.get_resource_name()}.")
            return self.post_delete(client)
        logger.error(f"Failed to delete {self.get_resource_type()}: {self.get_resource_name()}")
        return self.resource_deleted

    def post_delete(self, docker_client: DockerApiClient) -> bool:
        return True
