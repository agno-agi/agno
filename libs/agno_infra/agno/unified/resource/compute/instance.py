"""
Unified compute instance resource for multi-cloud VM/instance management.

This module provides a consistent interface for creating and managing virtual machines
across 60+ cloud providers using Apache Libcloud with native SDK fallback.
"""

from typing import Any, ClassVar, Dict, List, Optional, Union

from agno.base.unified import UnifiedResource
from agno.cli.console import print_info
from agno.utilities.logging import logger

try:
    from libcloud.compute.base import Node, NodeDriver, NodeImage, NodeLocation, NodeSize

    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False


class UnifiedInstance(UnifiedResource):
    """
    Unified compute instance resource that works across multiple cloud providers.

    This class provides a consistent interface for managing VM instances across
    AWS EC2, GCP Compute Engine, Azure VMs, DigitalOcean Droplets, and 60+ other providers.

    Attributes:
        size: Instance size/flavor (e.g., 'small', 'medium', 'large', or provider-specific)
        image: Operating system image (e.g., 'ubuntu-22.04', 'debian-11', or image ID)
        location: Deployment location/region/datacenter
        ssh_key: SSH key name or content for access
        security_groups: List of security group names/IDs
        tags: Resource tags/labels
        user_data: Cloud-init script or startup configuration
        network: Network/VPC to deploy in
        assign_public_ip: Whether to assign public IP address

    Example:
        # Create Ubuntu VM on GCP
        vm = UnifiedInstance(
            name="my-vm",
            provider="gcp",
            size="medium",
            image="ubuntu-22.04",
            location="us-central1-a"
        )
        vm.create()

        # Same code works on AWS
        vm = UnifiedInstance(
            name="my-vm",
            provider="aws",
            size="medium",
            image="ubuntu-22.04",
            location="us-east-1"
        )
        vm.create()
    """

    resource_type: str = "UnifiedInstance"
    resource_type_list: List[str] = ["instance", "vm", "node", "droplet"]

    # Instance configuration
    size: Optional[str] = None  # Instance size (small, medium, large, or provider-specific)
    image: Optional[str] = None  # OS image name or ID
    location: Optional[str] = None  # Region/zone/datacenter

    # Network configuration
    network: Optional[str] = None  # Network/VPC name or ID
    security_groups: Optional[List[str]] = None  # Security group names/IDs
    assign_public_ip: bool = True  # Assign public IP

    # Access configuration
    ssh_key: Optional[str] = None  # SSH key name or content
    ssh_key_content: Optional[str] = None  # SSH public key content

    # Metadata
    tags: Optional[Dict[str, str]] = None  # Resource tags
    user_data: Optional[str] = None  # Cloud-init script

    # Provider-specific attributes
    provider_specific: Optional[Dict[str, Any]] = None  # Extra provider-specific options

    # Size mapping for common sizes across providers
    SIZE_MAP: ClassVar[Dict[str, Dict[str, str]]] = {
        "nano": {
            "aws": "t2.nano",
            "gcp": "f1-micro",
            "azure": "Standard_A0",
            "digitalocean": "s-1vcpu-512mb-10gb",
            "linode": "g6-nanode-1",
        },
        "micro": {
            "aws": "t2.micro",
            "gcp": "f1-micro",
            "azure": "Standard_A1",
            "digitalocean": "s-1vcpu-1gb",
            "linode": "g6-nanode-1",
        },
        "small": {
            "aws": "t2.small",
            "gcp": "e2-small",
            "azure": "Standard_B1s",
            "digitalocean": "s-1vcpu-2gb",
            "linode": "g6-standard-1",
        },
        "medium": {
            "aws": "t2.medium",
            "gcp": "e2-medium",
            "azure": "Standard_B2s",
            "digitalocean": "s-2vcpu-4gb",
            "linode": "g6-standard-2",
        },
        "large": {
            "aws": "t2.large",
            "gcp": "e2-standard-2",
            "azure": "Standard_B4ms",
            "digitalocean": "s-4vcpu-8gb",
            "linode": "g6-standard-4",
        },
        "xlarge": {
            "aws": "t2.xlarge",
            "gcp": "e2-standard-4",
            "azure": "Standard_D4s_v3",
            "digitalocean": "s-8vcpu-16gb",
            "linode": "g6-standard-6",
        },
    }

    # Common image name mapping
    IMAGE_MAP: ClassVar[Dict[str, Dict[str, str]]] = {
        "ubuntu-22.04": {
            "aws": "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*",
            "gcp": "ubuntu-2204-lts",
            "azure": "Canonical:0001-com-ubuntu-server-jammy:22_04-lts:latest",
            "digitalocean": "ubuntu-22-04-x64",
        },
        "ubuntu-20.04": {
            "aws": "ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*",
            "gcp": "ubuntu-2004-lts",
            "azure": "Canonical:0001-com-ubuntu-server-focal:20_04-lts:latest",
            "digitalocean": "ubuntu-20-04-x64",
        },
        "debian-11": {
            "aws": "debian-11-amd64-*",
            "gcp": "debian-11",
            "azure": "Debian:debian-11:11:latest",
            "digitalocean": "debian-11-x64",
        },
        "centos-8": {
            "aws": "CentOS 8*",
            "gcp": "centos-8",
            "azure": "OpenLogic:CentOS:8_5:latest",
            "digitalocean": "centos-8-x64",
        },
    }

    def _get_provider_size(self, driver: NodeDriver) -> Optional[NodeSize]:
        """
        Get the appropriate instance size for the provider.

        Args:
            driver: Libcloud node driver

        Returns:
            NodeSize object or None
        """
        if not self.size:
            logger.error("Instance size not specified")
            return None

        # Check if size is a common name that needs mapping
        provider_name = self.get_provider_name()
        if self.size.lower() in self.SIZE_MAP:
            size_map = self.SIZE_MAP[self.size.lower()]
            provider_size_name = size_map.get(self.provider.lower())
            if provider_size_name:
                logger.debug(f"Mapped size '{self.size}' to '{provider_size_name}' for {provider_name}")
                self.size = provider_size_name

        # Get all available sizes from provider
        try:
            sizes = driver.list_sizes()
            logger.debug(f"Found {len(sizes)} available sizes for {provider_name}")

            # Try exact match first
            for size in sizes:
                if size.id == self.size or size.name == self.size:
                    logger.info(f"Selected size: {size.name} (ID: {size.id})")
                    return size

            # Try partial match
            for size in sizes:
                if self.size.lower() in size.id.lower() or self.size.lower() in size.name.lower():
                    logger.info(f"Matched size: {size.name} (ID: {size.id})")
                    return size

            logger.error(f"Size '{self.size}' not found for provider {provider_name}")
            logger.info(f"Available sizes: {[s.id for s in sizes[:10]]}")
            return None

        except Exception as e:
            logger.error(f"Failed to get sizes: {e}")
            return None

    def _get_provider_image(self, driver: NodeDriver) -> Optional[NodeImage]:
        """
        Get the appropriate OS image for the provider.

        Args:
            driver: Libcloud node driver

        Returns:
            NodeImage object or None
        """
        if not self.image:
            logger.error("OS image not specified")
            return None

        # Check if image is a common name that needs mapping
        provider_name = self.get_provider_name()
        if self.image.lower() in self.IMAGE_MAP:
            image_map = self.IMAGE_MAP[self.image.lower()]
            provider_image_name = image_map.get(self.provider.lower())
            if provider_image_name:
                logger.debug(f"Mapped image '{self.image}' to '{provider_image_name}' for {provider_name}")
                self.image = provider_image_name

        # For DigitalOcean, use get_image() with slug instead of listing all images
        if provider_name == "DIGITAL_OCEAN":
            try:
                logger.debug(f"Using DigitalOcean image slug: {self.image}")
                image = driver.get_image(self.image)
                if image:
                    logger.info(f"Selected image: {image.name} (ID: {image.id})")
                    return image
            except Exception as e:
                logger.error(f"Failed to get DigitalOcean image by slug: {e}")
                # Fall through to standard image search

        # Get all available images from provider
        try:
            images = driver.list_images()
            logger.debug(f"Found {len(images)} available images for {provider_name}")

            # Try exact match first
            for image in images:
                if image.id == self.image or image.name == self.image:
                    logger.info(f"Selected image: {image.name} (ID: {image.id})")
                    return image

            # Try partial match
            for image in images:
                if self.image.lower() in image.id.lower() or self.image.lower() in image.name.lower():
                    logger.info(f"Matched image: {image.name} (ID: {image.id})")
                    return image

            logger.error(f"Image '{self.image}' not found for provider {provider_name}")
            logger.debug(f"Sample available images: {[img.id for img in images[:10]]}")
            return None

        except Exception as e:
            logger.error(f"Failed to get images: {e}")
            return None

    def _get_provider_location(self, driver: NodeDriver) -> Optional[NodeLocation]:
        """
        Get the appropriate location/region for the provider.

        Args:
            driver: Libcloud node driver

        Returns:
            NodeLocation object or None if not required by provider
        """
        if not self.location and not self.provider_region:
            # Location is optional for some providers
            return None

        location_name = self.location or self.provider_region

        try:
            locations = driver.list_locations()

            # Some providers don't support locations
            if not locations:
                return None

            logger.debug(f"Found {len(locations)} available locations")

            # Try exact match first
            for loc in locations:
                if loc.id == location_name or loc.name == location_name:
                    logger.info(f"Selected location: {loc.name} (ID: {loc.id})")
                    return loc

            # Try partial match
            for loc in locations:
                if location_name.lower() in loc.id.lower() or location_name.lower() in loc.name.lower():
                    logger.info(f"Matched location: {loc.name} (ID: {loc.id})")
                    return loc

            logger.warning(f"Location '{location_name}' not found, using default")
            return None

        except Exception as e:
            logger.debug(f"Failed to get locations (might not be supported): {e}")
            return None

    def _read(self, driver: NodeDriver) -> Optional[Node]:
        """
        Read instance from cloud provider.

        Args:
            driver: Libcloud node driver

        Returns:
            Node object if found, None otherwise
        """
        logger.debug(f"Reading instance: {self.get_resource_name()}")

        try:
            nodes = driver.list_nodes()

            for node in nodes:
                if node.name == self.name:
                    logger.info(f"Found instance: {node.name} (ID: {node.id}, State: {node.state})")
                    self.active_resource = node
                    return node

            logger.debug(f"Instance {self.name} not found")
            return None

        except Exception as e:
            logger.error(f"Failed to read instance: {e}")
            return None

    def _create(self, driver: NodeDriver) -> bool:
        """
        Create instance on cloud provider.

        Args:
            driver: Libcloud node driver

        Returns:
            True if created successfully, False otherwise
        """
        print_info(f"Creating {self.get_resource_type()}: {self.get_resource_name()}")

        try:
            # Get size
            size = self._get_provider_size(driver)
            if not size:
                return False

            # Get image
            image = self._get_provider_image(driver)
            if not image:
                return False

            # Get location (optional)
            location = self._get_provider_location(driver)

            # Build creation parameters
            create_params: Dict[str, Any] = {
                "name": self.name,
                "size": size,
                "image": image,
            }

            if location:
                create_params["location"] = location

            # Add SSH key if provided
            if self.ssh_key:
                create_params["ex_keyname"] = self.ssh_key

            # Add user data if provided
            if self.user_data:
                create_params["ex_userdata"] = self.user_data

            # Add provider-specific parameters
            if self.provider_specific:
                create_params.update(self.provider_specific)

            # Create node
            logger.debug(f"Creating node with params: {list(create_params.keys())}")
            node = driver.create_node(**create_params)

            if node:
                logger.info(f"Instance created: {node.name} (ID: {node.id})")
                self.active_resource = node
                return True
            else:
                logger.error("Failed to create instance: no node returned")
                return False

        except Exception as e:
            logger.error(f"Failed to create instance: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return False

    def _update(self, driver: NodeDriver) -> bool:
        """
        Update instance on cloud provider.

        Note: Libcloud has limited update support. Most changes require recreation.

        Args:
            driver: Libcloud node driver

        Returns:
            True if updated successfully, False otherwise
        """
        logger.warning("Instance updates are limited in Libcloud. Consider using native SDK for advanced updates.")

        # For most providers, updates mean restarting or resizing
        # which would require provider-specific implementation
        return True

    def _delete(self, driver: NodeDriver) -> bool:
        """
        Delete instance from cloud provider.

        Args:
            driver: Libcloud node driver

        Returns:
            True if deleted successfully, False otherwise
        """
        print_info(f"Deleting {self.get_resource_type()}: {self.get_resource_name()}")

        try:
            # Get the node
            node = self.active_resource or self._read(driver)

            if not node:
                logger.error(f"Instance {self.name} not found")
                return False

            # Delete the node
            result = driver.destroy_node(node)

            if result:
                logger.info(f"Instance deleted: {node.name} (ID: {node.id})")
                self.active_resource = None
                return True
            else:
                logger.error("Failed to delete instance")
                return False

        except Exception as e:
            logger.error(f"Failed to delete instance: {e}")
            return False

    def get_public_ips(self) -> List[str]:
        """Get public IP addresses of the instance."""
        if self.active_resource and hasattr(self.active_resource, "public_ips"):
            return self.active_resource.public_ips
        return []

    def get_private_ips(self) -> List[str]:
        """Get private IP addresses of the instance."""
        if self.active_resource and hasattr(self.active_resource, "private_ips"):
            return self.active_resource.private_ips
        return []

    def get_state(self) -> Optional[str]:
        """Get current state of the instance."""
        if self.active_resource and hasattr(self.active_resource, "state"):
            return str(self.active_resource.state)
        return None

    def start(self) -> bool:
        """Start a stopped instance."""
        logger.warning("Start operation not universally supported in Libcloud")
        return False

    def stop(self) -> bool:
        """Stop a running instance."""
        logger.warning("Stop operation not universally supported in Libcloud")
        return False

    def reboot(self) -> bool:
        """Reboot the instance."""
        driver = self.get_libcloud_driver()
        if not driver or not self.active_resource:
            return False

        try:
            result = driver.reboot_node(self.active_resource)
            logger.info(f"Instance rebooted: {self.name}")
            return result
        except Exception as e:
            logger.error(f"Failed to reboot instance: {e}")
            return False
