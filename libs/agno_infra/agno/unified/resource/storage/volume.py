"""
Unified block storage volume resource for multi-cloud deployments.

This module provides a consistent interface for managing block storage volumes
(EBS-like) across AWS, GCP, Azure, and other providers.
"""

from typing import Any, ClassVar, Dict, List, Optional

from agno.base.unified import UnifiedResource
from agno.cli.console import print_info
from agno.utilities.logging import logger

try:
    from libcloud.compute.base import NodeDriver, StorageVolume

    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False


class UnifiedVolume(UnifiedResource):
    """
    Unified block storage volume resource across cloud providers.

    This provides EBS-compatible volume management across AWS, GCP, Azure, and more.

    Attributes:
        size: Volume size in GB
        volume_type: Type of volume (e.g., 'gp3', 'pd-standard', 'Standard_LRS')
        iops: IOPS for high-performance volumes
        encrypted: Enable encryption
        snapshot_id: Create from snapshot
        availability_zone: AZ/zone for volume
        tags: Resource tags

    Example:
        # Create volume on any provider
        volume = UnifiedVolume(
            name="my-data-volume",
            provider="aws",
            size=100,  # 100 GB
            volume_type="gp3",
            encrypted=True
        )
        volume.create()

        # Attach to instance
        volume.attach(instance_id="i-1234567890")
    """

    resource_type: str = "UnifiedVolume"
    resource_type_list: List[str] = ["volume", "disk", "storage"]

    # Volume configuration
    size: int  # Size in GB (required)
    volume_type: Optional[str] = None  # Volume type (provider-specific or mapped)
    iops: Optional[int] = None  # IOPS for performance
    throughput: Optional[int] = None  # Throughput in MB/s
    encrypted: bool = False  # Enable encryption
    snapshot_id: Optional[str] = None  # Create from snapshot
    availability_zone: Optional[str] = None  # AZ/zone
    tags: Optional[Dict[str, str]] = None  # Resource tags

    # Attachment info
    attached_to: Optional[str] = None  # Instance ID if attached
    device_name: Optional[str] = None  # Device name (e.g., /dev/sdf)

    # Volume type mapping for common types
    VOLUME_TYPE_MAP: ClassVar[Dict[str, Dict[str, str]]] = {
        "standard": {
            "aws": "standard",
            "gcp": "pd-standard",
            "azure": "Standard_LRS",
            "digitalocean": "standard",
        },
        "ssd": {
            "aws": "gp3",
            "gcp": "pd-ssd",
            "azure": "Premium_LRS",
            "digitalocean": "ssd",
        },
        "high-performance": {
            "aws": "io2",
            "gcp": "pd-extreme",
            "azure": "UltraSSD_LRS",
        },
    }

    def _get_provider_volume_type(self) -> Optional[str]:
        """Get the appropriate volume type for the provider."""
        if not self.volume_type:
            return None

        # Check if volume type is a common name that needs mapping
        provider_name = self.provider.lower() if self.provider else None
        if self.volume_type.lower() in self.VOLUME_TYPE_MAP:
            type_map = self.VOLUME_TYPE_MAP[self.volume_type.lower()]
            provider_type = type_map.get(provider_name)
            if provider_type:
                logger.debug(f"Mapped volume type '{self.volume_type}' to '{provider_type}' for {provider_name}")
                return provider_type

        # Return as-is if not in map (provider-specific type)
        return self.volume_type

    def _read(self, driver: NodeDriver) -> Optional[StorageVolume]:
        """Read volume from cloud provider."""
        logger.debug(f"Reading volume: {self.name}")

        try:
            volumes = driver.list_volumes()

            for volume in volumes:
                if volume.name == self.name:
                    logger.info(f"Found volume: {volume.name} (ID: {volume.id}, Size: {volume.size}GB)")
                    self.active_resource = volume
                    return volume

            logger.debug(f"Volume {self.name} not found")
            return None

        except Exception as e:
            logger.error(f"Failed to read volume: {e}")
            return None

    def _create(self, driver: NodeDriver) -> bool:
        """Create volume on cloud provider."""
        print_info(f"Creating {self.get_resource_type()}: {self.name}")

        try:
            # Get provider-specific volume type
            volume_type = self._get_provider_volume_type()

            # Build creation parameters
            create_params: Dict[str, Any] = {
                "size": self.size,
                "name": self.name,
            }

            # Add location if specified
            if self.availability_zone or self.provider_region:
                location_name = self.availability_zone or self.provider_region
                try:
                    locations = driver.list_locations()
                    for loc in locations:
                        if location_name in (loc.id, loc.name):
                            create_params["location"] = loc
                            break
                except Exception as e:
                    logger.debug(f"Could not get location: {e}")

            # Add snapshot if specified
            if self.snapshot_id:
                # Note: Snapshot support varies by provider
                create_params["ex_snapshot"] = self.snapshot_id

            # Add provider-specific parameters
            if volume_type:
                create_params["ex_volume_type"] = volume_type

            if self.iops:
                create_params["ex_iops"] = self.iops

            if self.encrypted:
                create_params["ex_encrypted"] = True

            # Create volume
            logger.debug(f"Creating volume with params: {list(create_params.keys())}")
            volume = driver.create_volume(**create_params)

            if volume:
                logger.info(f"Volume created: {volume.name} (ID: {volume.id}, Size: {volume.size}GB)")
                self.active_resource = volume
                return True
            else:
                logger.error("Failed to create volume: no volume returned")
                return False

        except Exception as e:
            logger.error(f"Failed to create volume: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return False

    def _update(self, driver: NodeDriver) -> bool:
        """Update volume configuration."""
        logger.warning("Volume update operations are limited in Libcloud")
        # Most updates require native SDK
        return True

    def _delete(self, driver: NodeDriver) -> bool:
        """Delete volume from cloud provider."""
        print_info(f"Deleting {self.get_resource_type()}: {self.name}")

        try:
            volume = self.active_resource or self._read(driver)

            if not volume:
                logger.error(f"Volume {self.name} not found")
                return False

            # Check if volume is attached
            if hasattr(volume, "extra") and volume.extra.get("status") == "in-use":
                logger.error(f"Volume {self.name} is attached. Detach before deleting.")
                return False

            # Delete volume
            result = driver.destroy_volume(volume)

            if result:
                logger.info(f"Volume deleted: {self.name}")
                self.active_resource = None
                return True
            else:
                logger.error("Failed to delete volume")
                return False

        except Exception as e:
            logger.error(f"Failed to delete volume: {e}")
            return False

    def attach(self, instance_id: str, device: Optional[str] = None) -> bool:
        """
        Attach volume to an instance.

        Args:
            instance_id: Instance ID to attach to
            device: Device name (e.g., /dev/sdf)

        Returns:
            True if attached successfully
        """
        driver = self.get_libcloud_driver()
        if not driver:
            return False

        print_info(f"Attaching volume {self.name} to instance {instance_id}")

        try:
            volume = self.active_resource or self._read(driver)

            if not volume:
                logger.error(f"Volume {self.name} not found")
                return False

            # Get the node
            nodes = driver.list_nodes()
            node = None
            for n in nodes:
                if n.id == instance_id or n.name == instance_id:
                    node = n
                    break

            if not node:
                logger.error(f"Instance {instance_id} not found")
                return False

            # Attach volume
            result = driver.attach_volume(node, volume, device=device)

            if result:
                logger.info(f"Volume attached: {self.name} to {instance_id}")
                self.attached_to = instance_id
                self.device_name = device
                return True
            else:
                logger.error("Failed to attach volume")
                return False

        except Exception as e:
            logger.error(f"Failed to attach volume: {e}")
            return False

    def detach(self, force: bool = False) -> bool:
        """
        Detach volume from instance.

        Args:
            force: Force detachment even if in use

        Returns:
            True if detached successfully
        """
        driver = self.get_libcloud_driver()
        if not driver:
            return False

        print_info(f"Detaching volume {self.name}")

        try:
            volume = self.active_resource or self._read(driver)

            if not volume:
                logger.error(f"Volume {self.name} not found")
                return False

            # Detach volume
            result = driver.detach_volume(volume)

            if result:
                logger.info(f"Volume detached: {self.name}")
                self.attached_to = None
                self.device_name = None
                return True
            else:
                logger.error("Failed to detach volume")
                return False

        except Exception as e:
            logger.error(f"Failed to detach volume: {e}")
            return False

    def create_snapshot(self, snapshot_name: Optional[str] = None) -> Optional[str]:
        """
        Create snapshot of the volume.

        Args:
            snapshot_name: Name for the snapshot (optional)

        Returns:
            Snapshot ID if created successfully
        """
        driver = self.get_libcloud_driver()
        if not driver:
            return None

        snapshot_name = snapshot_name or f"{self.name}-snapshot"
        print_info(f"Creating snapshot: {snapshot_name}")

        try:
            volume = self.active_resource or self._read(driver)

            if not volume:
                logger.error(f"Volume {self.name} not found")
                return None

            # Create snapshot (may not be supported by all providers)
            snapshot = driver.create_volume_snapshot(volume, name=snapshot_name)

            if snapshot:
                logger.info(f"Snapshot created: {snapshot.id}")
                return snapshot.id
            else:
                logger.error("Failed to create snapshot")
                return None

        except Exception as e:
            logger.warning(f"Snapshot creation not supported or failed: {e}")
            return None

    def resize(self, new_size: int) -> bool:
        """
        Resize volume (increase size only).

        Args:
            new_size: New size in GB (must be larger than current)

        Returns:
            True if resized successfully
        """
        if new_size <= self.size:
            logger.error(f"New size ({new_size}GB) must be larger than current size ({self.size}GB)")
            return False

        logger.warning("Volume resize not universally supported in Libcloud. Use native SDK for advanced operations.")
        return False

    def get_state(self) -> Optional[str]:
        """Get current state of the volume."""
        if self.active_resource:
            return self.active_resource.state if hasattr(self.active_resource, "state") else "available"
        return None

    def is_attached(self) -> bool:
        """Check if volume is attached to an instance."""
        return self.attached_to is not None
