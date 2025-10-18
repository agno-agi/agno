"""
Provider factory and routing system for unified multi-cloud resources.

This module handles provider detection, credential management, and routing
between Libcloud abstraction and native SDK implementations.
"""

from enum import Enum
from typing import Any, Dict, Optional, Type

from agno.utilities.logging import logger

try:
    from libcloud.compute.types import Provider as ComputeProvider
    from libcloud.storage.types import Provider as StorageProvider

    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False


class ProviderType(str, Enum):
    """Supported cloud provider types."""

    # Major cloud providers
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"

    # Developer-friendly clouds
    DIGITALOCEAN = "digitalocean"
    LINODE = "linode"
    VULTR = "vultr"

    # Enterprise/private clouds
    OPENSTACK = "openstack"
    VMWARE = "vmware"
    CLOUDSTACK = "cloudstack"

    # Other popular providers
    RACKSPACE = "rackspace"
    ALIBABA = "alibaba"
    IBM = "ibm"
    ORACLE = "oracle"

    # Add more as needed


class ResourceType(str, Enum):
    """Types of cloud resources."""

    COMPUTE = "compute"  # VMs, instances, containers
    STORAGE = "storage"  # Object storage, block storage
    NETWORK = "network"  # Load balancers, security groups
    DNS = "dns"  # DNS management
    CONTAINER = "container"  # Container orchestration
    BACKUP = "backup"  # Backup services


class ProviderCapability:
    """
    Defines capabilities for each provider and resource type.

    This helps route requests to either Libcloud or native SDK based on
    feature support and limitations.
    """

    # Provider capability matrix
    CAPABILITIES = {
        ProviderType.AWS: {
            ResourceType.COMPUTE: {"libcloud": True, "advanced_features": True, "native_sdk": "boto3"},
            ResourceType.STORAGE: {"libcloud": True, "advanced_features": True, "native_sdk": "boto3"},
            ResourceType.NETWORK: {"libcloud": True, "advanced_features": True, "native_sdk": "boto3"},
            ResourceType.DNS: {"libcloud": True, "advanced_features": True, "native_sdk": "boto3"},
        },
        ProviderType.GCP: {
            ResourceType.COMPUTE: {"libcloud": True, "advanced_features": True, "native_sdk": "google-cloud"},
            ResourceType.STORAGE: {"libcloud": True, "advanced_features": True, "native_sdk": "google-cloud"},
            ResourceType.NETWORK: {"libcloud": True, "advanced_features": True, "native_sdk": "google-cloud"},
        },
        ProviderType.AZURE: {
            ResourceType.COMPUTE: {"libcloud": True, "advanced_features": True, "native_sdk": "azure-sdk"},
            ResourceType.STORAGE: {"libcloud": True, "advanced_features": True, "native_sdk": "azure-sdk"},
            ResourceType.NETWORK: {"libcloud": True, "advanced_features": True, "native_sdk": "azure-sdk"},
        },
        ProviderType.DIGITALOCEAN: {
            ResourceType.COMPUTE: {"libcloud": True, "advanced_features": False, "native_sdk": None},
            ResourceType.STORAGE: {"libcloud": True, "advanced_features": False, "native_sdk": None},
        },
        ProviderType.LINODE: {
            ResourceType.COMPUTE: {"libcloud": True, "advanced_features": False, "native_sdk": None},
            ResourceType.STORAGE: {"libcloud": True, "advanced_features": False, "native_sdk": None},
        },
        ProviderType.OPENSTACK: {
            ResourceType.COMPUTE: {"libcloud": True, "advanced_features": True, "native_sdk": "python-openstackclient"},
            ResourceType.STORAGE: {"libcloud": True, "advanced_features": True, "native_sdk": "python-swiftclient"},
        },
    }

    @classmethod
    def supports_libcloud(cls, provider: str, resource_type: str) -> bool:
        """Check if provider/resource combination supports Libcloud."""
        try:
            provider_enum = ProviderType(provider.lower())
            resource_enum = ResourceType(resource_type.lower())

            capabilities = cls.CAPABILITIES.get(provider_enum, {}).get(resource_enum, {})
            return capabilities.get("libcloud", False)
        except (ValueError, KeyError):
            return False

    @classmethod
    def has_advanced_features(cls, provider: str, resource_type: str) -> bool:
        """Check if provider has advanced features requiring native SDK."""
        try:
            provider_enum = ProviderType(provider.lower())
            resource_enum = ResourceType(resource_type.lower())

            capabilities = cls.CAPABILITIES.get(provider_enum, {}).get(resource_enum, {})
            return capabilities.get("advanced_features", False)
        except (ValueError, KeyError):
            return False

    @classmethod
    def get_native_sdk(cls, provider: str, resource_type: str) -> Optional[str]:
        """Get the native SDK name for provider/resource if available."""
        try:
            provider_enum = ProviderType(provider.lower())
            resource_enum = ResourceType(resource_type.lower())

            capabilities = cls.CAPABILITIES.get(provider_enum, {}).get(resource_enum, {})
            return capabilities.get("native_sdk")
        except (ValueError, KeyError):
            return None


class ProviderFactory:
    """
    Factory for creating and managing cloud provider connections.

    This handles provider detection, credential loading, and driver
    initialization for both Libcloud and native SDKs.
    """

    def __init__(self):
        """Initialize provider factory."""
        self._driver_cache: Dict[str, Any] = {}

    def get_driver(
        self, provider: str, resource_type: str = "compute", credentials: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Optional[Any]:
        """
        Get a Libcloud driver for the specified provider and resource type.

        Args:
            provider: Provider name (e.g., 'aws', 'gcp', 'azure')
            resource_type: Type of resource driver to get
            credentials: Provider-specific credentials
            **kwargs: Additional driver arguments

        Returns:
            Initialized Libcloud driver or None if not available
        """
        if not LIBCLOUD_AVAILABLE:
            logger.error("Apache Libcloud not installed")
            return None

        # Check cache
        cache_key = f"{provider}:{resource_type}"
        if cache_key in self._driver_cache:
            return self._driver_cache[cache_key]

        # Check if provider supports Libcloud
        if not ProviderCapability.supports_libcloud(provider, resource_type):
            logger.warning(f"Provider {provider} does not support Libcloud for {resource_type}")
            return None

        # Get driver class and initialize
        try:
            from libcloud.compute.providers import get_driver as get_compute_driver
            from libcloud.storage.providers import get_driver as get_storage_driver

            # Map provider name to Libcloud constant
            provider_map = {
                "aws": "EC2",
                "gcp": "GCE",
                "azure": "AZURE_ARM",
                "digitalocean": "DIGITAL_OCEAN",
                "linode": "LINODE",
                "vultr": "VULTR",
                "openstack": "OPENSTACK",
                "rackspace": "RACKSPACE",
                "vmware": "VSPHERE",
                "cloudstack": "CLOUDSTACK",
            }

            provider_const_name = provider_map.get(provider.lower())
            if not provider_const_name:
                logger.error(f"Unknown provider: {provider}")
                return None

            # Get appropriate driver
            if resource_type == "compute":
                provider_const = getattr(ComputeProvider, provider_const_name)
                driver_class = get_compute_driver(provider_const)
            elif resource_type == "storage":
                provider_const = getattr(StorageProvider, provider_const_name)
                driver_class = get_storage_driver(provider_const)
            else:
                logger.error(f"Unsupported resource type: {resource_type}")
                return None

            # Get credentials
            if credentials is None:
                credentials = self._get_credentials(provider, **kwargs)

            # Initialize driver
            driver = driver_class(**credentials, **kwargs)

            # Cache the driver
            self._driver_cache[cache_key] = driver

            return driver

        except Exception as e:
            logger.error(f"Failed to initialize driver for {provider}/{resource_type}: {e}")
            return None

    def _get_credentials(self, provider: str, **kwargs) -> Dict[str, Any]:
        """
        Load credentials for the specified provider.

        Credentials are loaded from:
        1. Explicit kwargs
        2. Environment variables
        3. Provider-specific credential files

        Args:
            provider: Provider name
            **kwargs: Explicit credential values

        Returns:
            Dictionary of credentials for driver initialization
        """
        from os import getenv

        provider = provider.lower()

        # AWS credentials
        if provider == "aws":
            return {
                "key": kwargs.get("aws_access_key_id") or getenv("AWS_ACCESS_KEY_ID", ""),
                "secret": kwargs.get("aws_secret_access_key") or getenv("AWS_SECRET_ACCESS_KEY", ""),
                "region": kwargs.get("region") or getenv("AWS_REGION", "us-east-1"),
            }

        # GCP credentials
        elif provider == "gcp":
            return {
                "user_id": kwargs.get("service_account_email") or getenv("GCE_SERVICE_ACCOUNT_EMAIL", ""),
                "key": kwargs.get("service_account_key") or getenv("GCE_SERVICE_ACCOUNT_KEY", ""),
                "project": kwargs.get("project_id") or getenv("GCE_PROJECT_ID", ""),
                "datacenter": kwargs.get("region") or getenv("GCE_REGION", "us-central1-a"),
            }

        # Azure credentials
        elif provider == "azure":
            return {
                "tenant_id": kwargs.get("tenant_id") or getenv("AZURE_TENANT_ID", ""),
                "subscription_id": kwargs.get("subscription_id") or getenv("AZURE_SUBSCRIPTION_ID", ""),
                "key": kwargs.get("client_id") or getenv("AZURE_CLIENT_ID", ""),
                "secret": kwargs.get("client_secret") or getenv("AZURE_CLIENT_SECRET", ""),
            }

        # DigitalOcean credentials
        elif provider == "digitalocean":
            return {
                "key": kwargs.get("access_token") or getenv("DIGITALOCEAN_ACCESS_TOKEN", ""),
            }

        # Linode credentials
        elif provider == "linode":
            return {
                "key": kwargs.get("api_key") or getenv("LINODE_API_KEY", ""),
            }

        # Vultr credentials
        elif provider == "vultr":
            return {
                "key": kwargs.get("api_key") or getenv("VULTR_API_KEY", ""),
            }

        # OpenStack credentials
        elif provider == "openstack":
            return {
                "ex_force_auth_url": kwargs.get("auth_url") or getenv("OS_AUTH_URL", ""),
                "ex_force_auth_version": kwargs.get("auth_version", "3.x"),
                "ex_tenant_name": kwargs.get("tenant_name") or getenv("OS_TENANT_NAME", ""),
                "ex_force_service_region": kwargs.get("region") or getenv("OS_REGION_NAME", ""),
            }

        # VMware/vSphere credentials
        elif provider == "vmware":
            return {
                "host": kwargs.get("host") or getenv("VSPHERE_HOST", ""),
                "username": kwargs.get("username") or getenv("VSPHERE_USERNAME", ""),
                "password": kwargs.get("password") or getenv("VSPHERE_PASSWORD", ""),
            }

        # Default empty credentials
        logger.warning(f"No credential configuration for provider: {provider}")
        return {}

    def get_native_sdk_client(self, provider: str, resource_type: str, **kwargs) -> Optional[Any]:
        """
        Get a native SDK client for advanced provider-specific features.

        Args:
            provider: Provider name
            resource_type: Type of resource
            **kwargs: Provider-specific arguments

        Returns:
            Native SDK client instance or None
        """
        native_sdk = ProviderCapability.get_native_sdk(provider, resource_type)

        if not native_sdk:
            logger.info(f"No native SDK available for {provider}/{resource_type}")
            return None

        try:
            # AWS (boto3)
            if provider.lower() == "aws" and native_sdk == "boto3":
                import boto3

                return boto3.client(
                    self._resource_type_to_aws_service(resource_type),
                    region_name=kwargs.get("region", "us-east-1"),
                    aws_access_key_id=kwargs.get("aws_access_key_id"),
                    aws_secret_access_key=kwargs.get("aws_secret_access_key"),
                )

            # GCP (google-cloud)
            elif provider.lower() == "gcp" and native_sdk == "google-cloud":
                # Import appropriate GCP client based on resource type
                if resource_type == "compute":
                    from google.cloud import compute_v1

                    return compute_v1.InstancesClient()
                elif resource_type == "storage":
                    from google.cloud import storage

                    return storage.Client()

            # Azure (azure-sdk)
            elif provider.lower() == "azure" and native_sdk == "azure-sdk":
                # Import appropriate Azure client based on resource type
                if resource_type == "compute":
                    from azure.identity import DefaultAzureCredential
                    from azure.mgmt.compute import ComputeManagementClient

                    credential = DefaultAzureCredential()
                    return ComputeManagementClient(credential, kwargs.get("subscription_id"))

            logger.warning(f"Native SDK client not implemented for {provider}/{native_sdk}")
            return None

        except ImportError as e:
            logger.error(f"Native SDK {native_sdk} not installed: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize native SDK client: {e}")
            return None

    def _resource_type_to_aws_service(self, resource_type: str) -> str:
        """Map resource type to AWS service name."""
        mapping = {
            "compute": "ec2",
            "storage": "s3",
            "network": "ec2",
            "dns": "route53",
            "container": "ecs",
        }
        return mapping.get(resource_type, "ec2")

    def should_use_native_sdk(self, provider: str, resource_type: str, feature: Optional[str] = None) -> bool:
        """
        Determine if native SDK should be used instead of Libcloud.

        Args:
            provider: Provider name
            resource_type: Type of resource
            feature: Specific feature being requested (optional)

        Returns:
            True if native SDK should be used, False to use Libcloud
        """
        # Use native SDK if:
        # 1. Provider has advanced features
        # 2. Specific feature is provider-specific
        # 3. Libcloud doesn't support the provider/resource combination

        if not ProviderCapability.supports_libcloud(provider, resource_type):
            return True

        if feature and ProviderCapability.has_advanced_features(provider, resource_type):
            # Check if feature is in advanced features list
            # This would require a more detailed feature matrix
            return False  # Default to Libcloud for now

        return False


# Singleton instance
provider_factory = ProviderFactory()
