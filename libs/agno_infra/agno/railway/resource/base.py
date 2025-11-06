"""Base class for Railway resources."""

from typing import Any, Optional

from agno.base.resource import InfraResource
from agno.cli.console import print_info
from agno.railway.api_client import RailwayApiClient
from agno.utilities.logging import logger


class RailwayResource(InfraResource):
    """Base class for Railway Resources.

    All Railway resources (projects, environments, services, etc.) inherit from this class
    and implement the CRUD operations.
    """

    # Railway-specific fields
    railway_id: Optional[str] = None  # Railway's UUID for this resource
    status: Optional[str] = None  # Resource status (varies by resource type)

    # API token (can be set per-resource or inherited from resources.py)
    railway_api_token: Optional[str] = None

    def get_railway_api_token(self) -> Optional[str]:
        """Get Railway API token with fallback priority."""
        # Priority 1: Use api_token from resource
        if self.railway_api_token:
            return self.railway_api_token

        # Priority 2: Get api_token from infra settings
        if self.infra_settings is not None and hasattr(self.infra_settings, "railway_api_token"):
            if self.infra_settings.railway_api_token is not None:
                self.railway_api_token = self.infra_settings.railway_api_token
                return self.railway_api_token

        # Priority 3: Get api_token from env
        from os import getenv

        railway_api_token_env = getenv("RAILWAY_API_TOKEN")
        if railway_api_token_env is not None:
            logger.debug("Using RAILWAY_API_TOKEN from environment")
            self.railway_api_token = railway_api_token_env
        return self.railway_api_token

    def get_railway_client(self) -> RailwayApiClient:
        """Get or create Railway API client."""
        api_token = self.get_railway_api_token()
        return RailwayApiClient(api_token=api_token)

    # Abstract methods to be implemented by subclasses

    def _read(self, railway_client: RailwayApiClient) -> Any:
        """Read resource from Railway. To be implemented by subclasses."""
        logger.warning(f"@_read method not defined for {self.get_resource_name()}")
        return True

    def _create(self, railway_client: RailwayApiClient) -> bool:
        """Create resource in Railway. To be implemented by subclasses."""
        logger.warning(f"@_create method not defined for {self.get_resource_name()}")
        return True

    def _update(self, railway_client: RailwayApiClient) -> bool:
        """Update resource in Railway. To be implemented by subclasses."""
        logger.warning(f"@_update method not defined for {self.get_resource_name()}")
        return True

    def _delete(self, railway_client: RailwayApiClient) -> bool:
        """Delete resource from Railway. To be implemented by subclasses."""
        logger.warning(f"@_delete method not defined for {self.get_resource_name()}")
        return True

    def _post_create(self, railway_client: RailwayApiClient) -> bool:
        """Post-create hook. To be implemented by subclasses if needed."""
        return True

    # Public interface methods

    def read(self, railway_client: Optional[RailwayApiClient] = None) -> Any:
        """Read the resource from Railway."""
        # Step 1: Use cached value if available
        if self.use_cache and self.active_resource is not None:
            return self.active_resource

        # Step 2: Skip resource read if skip_read = True
        if self.skip_read:
            print_info(f"Skipping read: {self.get_resource_name()}")
            return True

        # Step 3: Read resource
        client = railway_client or self.get_railway_client()
        logger.debug(f"Reading {self.get_resource_type()}: {self.get_resource_name()}")

        try:
            self.active_resource = self._read(client)
            return self.active_resource
        except Exception as e:
            logger.error(f"Failed to read {self.get_resource_name()}: {e}")
            return None

    def is_active(self, railway_client: Optional[RailwayApiClient] = None) -> bool:
        """Check if resource is active in Railway."""
        if self.active_resource is None:
            self.read(railway_client)
        return self.active_resource is not None

    def create(self, railway_client: Optional[RailwayApiClient] = None) -> bool:
        """Create resource in Railway."""
        # Step 1: Skip resource creation if skip_create = True
        if self.skip_create:
            print_info(f"Skipping create: {self.get_resource_name()}")
            return True

        # Step 2: Check if resource already exists
        client = railway_client or self.get_railway_client()
        if self.is_active(client):
            if self.force:
                logger.warning(f"{self.get_resource_name()} exists, deleting for re-creation")
                self.delete(client)
            else:
                print_info(f"{self.get_resource_name()} already exists")
                return True

        # Step 3: Create resource
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")
        try:
            self.resource_created = self._create(client)
            if self.resource_created:
                # Re-read to get full resource details
                self.active_resource = self._read(client)

                # Save output to file if needed
                if self.save_output:
                    self.save_output_file()

                # Run post-create hook
                self._post_create(client)

                logger.info(f"Created {self.get_resource_type()}: {self.get_resource_name()}")
            return self.resource_created
        except Exception as e:
            logger.error(f"Failed to create {self.get_resource_name()}: {e}")
            return False

    def update(self, railway_client: Optional[RailwayApiClient] = None) -> bool:
        """Update resource in Railway."""
        # Step 1: Skip resource update if skip_update = True
        if self.skip_update:
            print_info(f"Skipping update: {self.get_resource_name()}")
            return True

        # Step 2: Update resource
        client = railway_client or self.get_railway_client()
        print_info(f"Updating {self.get_resource_type()}: {self.get_resource_name()}")

        try:
            self.resource_updated = self._update(client)
            if self.resource_updated:
                # Re-read to get updated resource details
                self.active_resource = self._read(client)

                # Save output to file if needed
                if self.save_output:
                    self.save_output_file()

                logger.info(f"Updated {self.get_resource_type()}: {self.get_resource_name()}")
            return self.resource_updated
        except Exception as e:
            logger.error(f"Failed to update {self.get_resource_name()}: {e}")
            return False

    def delete(self, railway_client: Optional[RailwayApiClient] = None) -> bool:
        """Delete resource from Railway."""
        # Step 1: Skip resource deletion if skip_delete = True
        if self.skip_delete:
            print_info(f"Skipping delete: {self.get_resource_name()}")
            return True

        # Step 2: Delete resource
        client = railway_client or self.get_railway_client()
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        try:
            self.resource_deleted = self._delete(client)
            if self.resource_deleted:
                # Clear active resource
                self.active_resource = None

                # Delete output file if needed
                if self.save_output:
                    self.delete_output_file()

                logger.info(f"Deleted {self.get_resource_type()}: {self.get_resource_name()}")
            return self.resource_deleted
        except Exception as e:
            logger.error(f"Failed to delete {self.get_resource_name()}: {e}")
            return False
