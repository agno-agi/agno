from typing import Any, Optional

from agno.aws.api_client import AwsApiClient
from agno.cli.console import print_info
from agno.infra.resource import InfraResource
from agno.utils.log import logger


class AwsResource(InfraResource):
    """Base class for AWS Resources."""

    service_name: str
    service_client: Optional[Any] = None
    service_resource: Optional[Any] = None

    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None

    aws_client: Optional[AwsApiClient] = None

    def get_aws_region(self) -> Optional[str]:
        # Priority 1: Use aws_region from resource
        if self.aws_region:
            return self.aws_region

        # Priority 2: Get aws_region from workspace settings
        if self.workspace_settings is not None and self.workspace_settings.aws_region is not None:
            self.aws_region = self.workspace_settings.aws_region
            return self.aws_region

        # Priority 3: Get aws_region from env
        from os import getenv

        from agno.constants import AWS_REGION_ENV_VAR

        aws_region_env = getenv(AWS_REGION_ENV_VAR)
        if aws_region_env is not None:
            logger.debug(f"{AWS_REGION_ENV_VAR}: {aws_region_env}")
            self.aws_region = aws_region_env
        return self.aws_region

    def get_aws_profile(self) -> Optional[str]:
        # Priority 1: Use aws_region from resource
        if self.aws_profile:
            return self.aws_profile

        # Priority 2: Get aws_profile from workspace settings
        if self.workspace_settings is not None and self.workspace_settings.aws_profile is not None:
            self.aws_profile = self.workspace_settings.aws_profile
            return self.aws_profile

        # Priority 3: Get aws_profile from env
        from os import getenv

        from agno.constants import AWS_PROFILE_ENV_VAR

        aws_profile_env = getenv(AWS_PROFILE_ENV_VAR)
        if aws_profile_env is not None:
            logger.debug(f"{AWS_PROFILE_ENV_VAR}: {aws_profile_env}")
            self.aws_profile = aws_profile_env
        return self.aws_profile

    def get_service_client(self, aws_client: AwsApiClient):
        from boto3 import session

        if self.service_client is None:
            boto3_session: session = aws_client.boto3_session
            self.service_client = boto3_session.client(service_name=self.service_name)
        return self.service_client

    def get_service_resource(self, aws_client: AwsApiClient):
        from boto3 import session

        if self.service_resource is None:
            boto3_session: session = aws_client.boto3_session
            self.service_resource = boto3_session.resource(service_name=self.service_name)
        return self.service_resource

    def get_aws_client(self) -> AwsApiClient:
        if self.aws_client is not None:
            return self.aws_client
        self.aws_client = AwsApiClient(aws_region=self.get_aws_region(), aws_profile=self.get_aws_profile())
        return self.aws_client

    def _read(self, aws_client: AwsApiClient) -> Any:
        logger.warning(f"@_read method not defined for {self.get_resource_name()}")
        return True

    def read(self, aws_client: Optional[AwsApiClient] = None) -> Any:
        """Reads the resource from Aws"""
        # Step 1: Use cached value if available
        if self.use_cache and self.active_resource is not None:
            return self.active_resource

        # Step 2: Skip resource creation if skip_read = True
        if self.skip_read:
            print_info(f"Skipping read: {self.get_resource_name()}")
            return True

        # Step 3: Read resource
        client: AwsApiClient = aws_client or self.get_aws_client()
        return self._read(client)

    def is_active(self, aws_client: AwsApiClient) -> bool:
        """Returns True if the resource is active on Aws"""
        _resource = self.read(aws_client=aws_client)
        return True if _resource is not None else False

    def _create(self, aws_client: AwsApiClient) -> bool:
        logger.warning(f"@_create method not defined for {self.get_resource_name()}")
        return True

    def create(self, aws_client: Optional[AwsApiClient] = None) -> bool:
        """Creates the resource on Aws"""

        # Step 1: Skip resource creation if skip_create = True
        if self.skip_create:
            print_info(f"Skipping create: {self.get_resource_name()}")
            return True

        # Step 2: Check if resource is active and use_cache = True
        client: AwsApiClient = aws_client or self.get_aws_client()
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

    def post_create(self, aws_client: AwsApiClient) -> bool:
        return True

    def _update(self, aws_client: AwsApiClient) -> Any:
        logger.warning(f"@_update method not defined for {self.get_resource_name()}")
        return True

    def update(self, aws_client: Optional[AwsApiClient] = None) -> bool:
        """Updates the resource on Aws"""

        # Step 1: Skip resource update if skip_update = True
        if self.skip_update:
            print_info(f"Skipping update: {self.get_resource_name()}")
            return True

        # Step 2: Update the resource
        client: AwsApiClient = aws_client or self.get_aws_client()
        if self.is_active(client):
            self.resource_updated = self._update(client)
        else:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} does not exist")
            return True

        # Step 3: Run post update steps
        if self.resource_updated:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} updated")
            if self.save_output:
                self.save_output_file()
            logger.debug(f"Running post-update for {self.get_resource_type()}: {self.get_resource_name()}")
            return self.post_update(client)
        logger.error(f"Failed to update {self.get_resource_type()}: {self.get_resource_name()}")
        return self.resource_updated

    def post_update(self, aws_client: AwsApiClient) -> bool:
        return True

    def _delete(self, aws_client: AwsApiClient) -> Any:
        logger.warning(f"@_delete method not defined for {self.get_resource_name()}")
        return True

    def delete(self, aws_client: Optional[AwsApiClient] = None) -> bool:
        """Deletes the resource from Aws"""

        # Step 1: Skip resource deletion if skip_delete = True
        if self.skip_delete:
            print_info(f"Skipping delete: {self.get_resource_name()}")
            return True

        # Step 2: Delete the resource
        client: AwsApiClient = aws_client or self.get_aws_client()
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

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        return True
