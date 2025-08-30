from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from agno.cloud.aws.s3.api_client import AwsApiClient
from agno.utils.log import logger


class AwsResource(BaseModel):
    """Base class for AWS Resources."""

    # Resource name (required)
    name: str

    # Resource type
    resource_type: Optional[str] = None
    active_resource: Optional[Any] = None

    skip_delete: bool = False
    skip_create: bool = False
    skip_read: bool = False
    skip_update: bool = False

    wait_for_create: bool = True
    wait_for_update: bool = True
    wait_for_delete: bool = True
    waiter_delay: int = 30
    waiter_max_attempts: int = 50
    save_output: bool = False
    use_cache: bool = True

    service_name: str
    service_client: Optional[Any] = None
    service_resource: Optional[Any] = None

    aws_region: Optional[str] = None
    aws_profile: Optional[str] = None

    aws_client: Optional[AwsApiClient] = None

    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    def get_resource_name(self) -> str:
        return self.name or self.__class__.__name__

    def get_resource_type(self) -> str:
        if self.resource_type is None:
            return self.__class__.__name__
        return self.resource_type

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

    def get_aws_region(self) -> Optional[str]:
        if self.aws_region:
            return self.aws_region

        from os import getenv

        aws_region_env = getenv("AWS_REGION")
        if aws_region_env is not None:
            logger.debug(f"{'AWS_REGION'}: {aws_region_env}")
            self.aws_region = aws_region_env
        return self.aws_region

    def get_aws_profile(self) -> Optional[str]:
        if self.aws_profile:
            return self.aws_profile

        from os import getenv

        aws_profile_env = getenv("AWS_PROFILE")
        if aws_profile_env is not None:
            logger.debug(f"{'AWS_PROFILE'}: {aws_profile_env}")
            self.aws_profile = aws_profile_env
        return self.aws_profile

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
            print(f"Skipping read: {self.get_resource_name()}")
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
            print(f"Skipping create: {self.get_resource_name()}")
            return True

        # Step 2: Check if resource is active and use_cache = True
        client: AwsApiClient = aws_client or self.get_aws_client()
        if self.use_cache and self.is_active(client):
            self.resource_created = True
            print(f"{self.get_resource_type()}: {self.get_resource_name()} already exists")
        # Step 3: Create the resource
        else:
            self.resource_created = self._create(client)
            if self.resource_created:
                print(f"{self.get_resource_type()}: {self.get_resource_name()} created")

        # Step 4: Run post create steps
        if self.resource_created:
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
            print(f"Skipping update: {self.get_resource_name()}")
            return True

        # Step 2: Update the resource
        client: AwsApiClient = aws_client or self.get_aws_client()
        if self.is_active(client):
            self.resource_updated = self._update(client)
        else:
            print(f"{self.get_resource_type()}: {self.get_resource_name()} does not exist")
            return True

        # Step 3: Run post update steps
        if self.resource_updated:
            print(f"{self.get_resource_type()}: {self.get_resource_name()} updated")
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
            print(f"Skipping delete: {self.get_resource_name()}")
            return True

        # Step 2: Delete the resource
        client: AwsApiClient = aws_client or self.get_aws_client()
        if self.is_active(client):
            self.resource_deleted = self._delete(client)
        else:
            print(f"{self.get_resource_type()}: {self.get_resource_name()} does not exist")
            return True

        # Step 3: Run post delete steps
        if self.resource_deleted:
            print(f"{self.get_resource_type()}: {self.get_resource_name()} deleted")
            logger.debug(f"Running post-delete for {self.get_resource_type()}: {self.get_resource_name()}.")
            return self.post_delete(client)
        logger.error(f"Failed to delete {self.get_resource_type()}: {self.get_resource_name()}")
        return self.resource_deleted

    def post_delete(self, aws_client: AwsApiClient) -> bool:
        return True
