"""
Unified base class for multi-cloud resources using Apache Libcloud abstraction.

This module provides the foundation for managing resources across 60+ cloud providers
with a consistent interface while maintaining the ability to fall back to native SDKs
for provider-specific features.
"""

from typing import Any, ClassVar, Dict, Optional, Type

from agno.base.resource import InfraResource
from agno.utilities.logging import logger

try:
    from libcloud.compute.base import Node, NodeDriver
    from libcloud.compute.providers import get_driver as get_compute_driver
    from libcloud.compute.types import Provider as ComputeProvider
    from libcloud.storage.base import Container, Object, StorageDriver
    from libcloud.storage.providers import get_driver as get_storage_driver
    from libcloud.storage.types import Provider as StorageProvider

    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False
    logger.warning(
        "Apache Libcloud not installed. Install with: pip install apache-libcloud\n"
        "Multi-cloud unified resources will not be available."
    )


class UnifiedResource(InfraResource):
    """
    Base class for unified multi-cloud resources using Apache Libcloud.

    This class provides a consistent interface for managing resources across
    multiple cloud providers. It uses Apache Libcloud for common operations
    and can fall back to native SDKs for provider-specific features.

    Attributes:
        provider: Cloud provider identifier (e.g., 'aws', 'gcp', 'azure', 'digitalocean')
        provider_credentials: Provider-specific authentication credentials
        provider_region: Region/location for resource deployment
        use_native_sdk: If True, falls back to native SDK instead of Libcloud
    """

    # Cloud provider configuration
    provider: Optional[str] = None
    provider_credentials: Optional[Dict[str, Any]] = None
    provider_region: Optional[str] = None

    # Resource configuration
    use_native_sdk: bool = False  # Fall back to native SDK for advanced features
    libcloud_driver: Optional[Any] = None  # Cached Libcloud driver instance

    # Provider mapping for common names to Libcloud constants
    PROVIDER_MAP: ClassVar[Dict[str, str]] = {
        # Compute providers
        "aws": "EC2",
        "ec2": "EC2",
        "gcp": "GCE",
        "gce": "GCE",
        "google": "GCE",
        "azure": "AZURE_ARM",
        "azure_arm": "AZURE_ARM",
        "digitalocean": "DIGITAL_OCEAN",
        "do": "DIGITAL_OCEAN",
        "linode": "LINODE",
        "vultr": "VULTR",
        "openstack": "OPENSTACK",
        "rackspace": "RACKSPACE",
        "cloudstack": "CLOUDSTACK",
        "vsphere": "VSPHERE",
        "vmware": "VSPHERE",
        # Add more as needed
    }

    # Storage provider mapping (some providers have different names for storage)
    STORAGE_PROVIDER_MAP: ClassVar[Dict[str, str]] = {
        "aws": "S3",
        "s3": "S3",
        "gcp": "GOOGLE_STORAGE",
        "google": "GOOGLE_STORAGE",
        "azure": "AZURE_BLOBS",
        "digitalocean": "DIGITALOCEAN_SPACES",
        "do": "DIGITALOCEAN_SPACES",
        # Add more as needed
    }

    def __init__(self, **data):
        """Initialize unified resource with provider validation."""
        super().__init__(**data)

        if not LIBCLOUD_AVAILABLE:
            logger.error(
                "Apache Libcloud is required for unified multi-cloud resources. "
                "Install with: pip install apache-libcloud"
            )

        # Validate provider is specified
        if self.provider is None:
            logger.warning(f"{self.__class__.__name__}: No provider specified")

    def get_provider_name(self) -> Optional[str]:
        """
        Get the standardized Libcloud provider name.

        Returns:
            Libcloud provider constant name (e.g., 'EC2', 'GCE', 'AZURE_ARM')
        """
        if self.provider is None:
            return None

        provider_lower = self.provider.lower()
        return self.PROVIDER_MAP.get(provider_lower, self.provider.upper())

    def get_libcloud_driver_class(self, driver_type: str = "compute") -> Optional[Type]:
        """
        Get the appropriate Libcloud driver class for this provider.

        Args:
            driver_type: Type of driver ('compute', 'storage', 'loadbalancer', 'dns')

        Returns:
            Libcloud driver class or None if not available
        """
        if not LIBCLOUD_AVAILABLE:
            return None

        if self.provider is None:
            logger.error("Provider not set")
            return None

        try:
            if driver_type == "compute":
                provider_name = self.get_provider_name()
                if provider_name:
                    provider_const = getattr(ComputeProvider, provider_name, None)
                    if provider_const:
                        return get_compute_driver(provider_const)
            elif driver_type == "storage":
                # Use storage-specific mapping
                provider_lower = self.provider.lower()
                storage_provider_name = self.STORAGE_PROVIDER_MAP.get(provider_lower)
                if storage_provider_name:
                    provider_const = getattr(StorageProvider, storage_provider_name, None)
                    if provider_const:
                        return get_storage_driver(provider_const)
                    else:
                        logger.error(f"Storage provider constant not found: {storage_provider_name}")
                else:
                    logger.error(f"No storage provider mapping for: {self.provider}")
            # Add more driver types as needed (loadbalancer, dns, container, backup)
            else:
                logger.error(f"Unsupported driver type: {driver_type}")

            return None
        except Exception as e:
            logger.error(f"Failed to get Libcloud driver: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def get_libcloud_driver(self, driver_type: str = "compute") -> Optional[Any]:
        """
        Get or create a Libcloud driver instance for this provider.

        Args:
            driver_type: Type of driver ('compute', 'storage', etc.)

        Returns:
            Initialized Libcloud driver instance or None
        """
        # Return cached driver if available
        if self.libcloud_driver is not None:
            return self.libcloud_driver

        # Get driver class
        driver_class = self.get_libcloud_driver_class(driver_type)
        if driver_class is None:
            return None

        # Initialize driver with credentials
        try:
            credentials = self._get_provider_credentials()
            self.libcloud_driver = driver_class(**credentials)
            return self.libcloud_driver
        except Exception as e:
            logger.error(f"Failed to initialize Libcloud driver: {e}")
            return None

    def _get_provider_credentials(self) -> Dict[str, Any]:
        """
        Get provider-specific credentials for Libcloud authentication.

        This method should be overridden by subclasses or configured via
        provider_credentials attribute for provider-specific auth.

        Returns:
            Dictionary of credentials for Libcloud driver initialization
        """
        if self.provider_credentials:
            return self.provider_credentials

        # Try to get credentials from environment or settings
        from os import getenv

        provider_name = self.get_provider_name()

        # AWS/EC2
        if provider_name == "EC2":
            return {
                "key": getenv("AWS_ACCESS_KEY_ID", ""),
                "secret": getenv("AWS_SECRET_ACCESS_KEY", ""),
                "region": self.provider_region or getenv("AWS_REGION", "us-east-1"),
            }

        # GCP/GCE
        elif provider_name == "GCE":
            return {
                "user_id": getenv("GCE_SERVICE_ACCOUNT_EMAIL", ""),
                "key": getenv("GCE_SERVICE_ACCOUNT_KEY", ""),
                "project": getenv("GCE_PROJECT_ID", ""),
                "datacenter": self.provider_region or getenv("GCE_REGION", "us-central1-a"),
            }

        # Azure
        elif provider_name == "AZURE_ARM":
            return {
                "tenant_id": getenv("AZURE_TENANT_ID", ""),
                "subscription_id": getenv("AZURE_SUBSCRIPTION_ID", ""),
                "key": getenv("AZURE_CLIENT_ID", ""),
                "secret": getenv("AZURE_CLIENT_SECRET", ""),
            }

        # DigitalOcean Compute
        elif provider_name == "DIGITAL_OCEAN":
            return {
                "key": getenv("DIGITALOCEAN_ACCESS_TOKEN", ""),
            }

        # DigitalOcean Spaces (S3-compatible storage)
        elif provider_name == "DIGITALOCEAN_SPACES":
            # Spaces uses separate access keys (not the personal access token)
            # Get from: https://cloud.digitalocean.com/account/api/tokens (Spaces tab)
            return {
                "key": getenv("DIGITALOCEAN_SPACES_ACCESS_KEY", getenv("SPACES_ACCESS_KEY", "")),
                "secret": getenv("DIGITALOCEAN_SPACES_SECRET_KEY", getenv("SPACES_SECRET_KEY", "")),
                "region": self.provider_region or getenv("DIGITALOCEAN_SPACES_REGION", "nyc3"),
            }

        # Default empty credentials (will likely fail)
        logger.warning(f"No credentials configuration for provider: {provider_name}")
        return {}

    def _read(self, client: Any = None) -> Any:
        """Read resource from cloud provider using Libcloud."""
        raise NotImplementedError(
            f"@_read method not implemented for {self.__class__.__name__}. "
            "Subclasses must implement this method."
        )

    def _create(self, client: Any = None) -> bool:
        """Create resource on cloud provider using Libcloud."""
        raise NotImplementedError(
            f"@_create method not implemented for {self.__class__.__name__}. "
            "Subclasses must implement this method."
        )

    def _update(self, client: Any = None) -> bool:
        """Update resource on cloud provider using Libcloud."""
        raise NotImplementedError(
            f"@_update method not implemented for {self.__class__.__name__}. "
            "Subclasses must implement this method."
        )

    def _delete(self, client: Any = None) -> bool:
        """Delete resource from cloud provider using Libcloud."""
        raise NotImplementedError(
            f"@_delete method not implemented for {self.__class__.__name__}. "
            "Subclasses must implement this method."
        )

    def read(self, client: Any = None) -> Any:
        """Read resource using Libcloud or native SDK."""
        # Use cached value if available
        if self.use_cache and self.active_resource is not None:
            return self.active_resource

        # Skip if requested
        if self.skip_read:
            from agno.cli.console import print_info

            print_info(f"Skipping read: {self.get_resource_name()}")
            return True

        # Use native SDK if requested
        if self.use_native_sdk:
            return self._read_native(client)

        # Use Libcloud
        driver = client or self.get_libcloud_driver()
        if driver is None:
            logger.error(f"Failed to get driver for {self.get_resource_name()}")
            return None

        return self._read(driver)

    def create(self, client: Any = None) -> bool:
        """Create resource using Libcloud or native SDK."""
        from agno.cli.console import print_info

        # Skip if requested
        if self.skip_create:
            print_info(f"Skipping create: {self.get_resource_name()}")
            return True

        # Get driver
        driver = client or self.get_libcloud_driver()
        if driver is None:
            logger.error(f"Failed to get driver for {self.get_resource_name()}")
            return False

        # Check if already exists
        if self.use_cache and self.is_active(driver):
            self.resource_created = True
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} already exists")
        else:
            # Use native SDK if requested
            if self.use_native_sdk:
                self.resource_created = self._create_native(driver)
            else:
                self.resource_created = self._create(driver)

            if self.resource_created:
                print_info(f"{self.get_resource_type()}: {self.get_resource_name()} created")

        # Post-create steps
        if self.resource_created:
            if self.save_output:
                self.save_output_file()
            return self.post_create(driver)

        logger.error(f"Failed to create {self.get_resource_type()}: {self.get_resource_name()}")
        return False

    def update(self, client: Any = None) -> bool:
        """Update resource using Libcloud or native SDK."""
        from agno.cli.console import print_info

        # Skip if requested
        if self.skip_update:
            print_info(f"Skipping update: {self.get_resource_name()}")
            return True

        # Get driver
        driver = client or self.get_libcloud_driver()
        if driver is None:
            logger.error(f"Failed to get driver for {self.get_resource_name()}")
            return False

        # Check if exists
        if not self.is_active(driver):
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} does not exist")
            return True

        # Use native SDK if requested
        if self.use_native_sdk:
            self.resource_updated = self._update_native(driver)
        else:
            self.resource_updated = self._update(driver)

        # Post-update steps
        if self.resource_updated:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} updated")
            if self.save_output:
                self.save_output_file()
            return self.post_update(driver)

        logger.error(f"Failed to update {self.get_resource_type()}: {self.get_resource_name()}")
        return False

    def delete(self, client: Any = None) -> bool:
        """Delete resource using Libcloud or native SDK."""
        from agno.cli.console import print_info

        # Skip if requested
        if self.skip_delete:
            print_info(f"Skipping delete: {self.get_resource_name()}")
            return True

        # Get driver
        driver = client or self.get_libcloud_driver()
        if driver is None:
            logger.error(f"Failed to get driver for {self.get_resource_name()}")
            return False

        # Check if exists
        if not self.is_active(driver):
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} does not exist")
            return True

        # Use native SDK if requested
        if self.use_native_sdk:
            self.resource_deleted = self._delete_native(driver)
        else:
            self.resource_deleted = self._delete(driver)

        # Post-delete steps
        if self.resource_deleted:
            print_info(f"{self.get_resource_type()}: {self.get_resource_name()} deleted")
            if self.save_output:
                self.delete_output_file()
            return self.post_delete(driver)

        logger.error(f"Failed to delete {self.get_resource_type()}: {self.get_resource_name()}")
        return False

    def is_active(self, client: Any = None) -> bool:
        """Check if resource exists on the cloud provider."""
        resource = self.read(client)
        return resource is not None

    # Native SDK fallback methods (to be overridden by subclasses)
    def _read_native(self, client: Any) -> Any:
        """Read using native SDK. Override in subclass for provider-specific implementation."""
        logger.warning(f"Native SDK read not implemented for {self.__class__.__name__}")
        return None

    def _create_native(self, client: Any) -> bool:
        """Create using native SDK. Override in subclass for provider-specific implementation."""
        logger.warning(f"Native SDK create not implemented for {self.__class__.__name__}")
        return False

    def _update_native(self, client: Any) -> bool:
        """Update using native SDK. Override in subclass for provider-specific implementation."""
        logger.warning(f"Native SDK update not implemented for {self.__class__.__name__}")
        return False

    def _delete_native(self, client: Any) -> bool:
        """Delete using native SDK. Override in subclass for provider-specific implementation."""
        logger.warning(f"Native SDK delete not implemented for {self.__class__.__name__}")
        return False

    # Post-operation hooks
    def post_create(self, driver: Any) -> bool:
        """Hook called after successful create operation."""
        return True

    def post_update(self, driver: Any) -> bool:
        """Hook called after successful update operation."""
        return True

    def post_delete(self, driver: Any) -> bool:
        """Hook called after successful delete operation."""
        return True
