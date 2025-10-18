"""
Unified object storage resources for multi-cloud S3-compatible storage.

This module provides a consistent interface for managing object storage
(buckets and objects) across AWS S3, GCS, Azure Blob Storage, and 20+ other providers.
"""

from typing import Any, Dict, List, Optional, Union

from agno.base.unified import UnifiedResource
from agno.cli.console import print_info
from agno.utilities.logging import logger

try:
    from libcloud.storage.base import Container, Object, StorageDriver
    from libcloud.storage.types import ContainerDoesNotExistError, ObjectDoesNotExistError

    LIBCLOUD_AVAILABLE = True
except ImportError:
    LIBCLOUD_AVAILABLE = False


class UnifiedBucket(UnifiedResource):
    """
    Unified bucket/container resource for object storage across cloud providers.

    This provides S3-compatible bucket management across AWS S3, Google Cloud Storage,
    Azure Blob Storage, DigitalOcean Spaces, and 20+ other providers.

    Attributes:
        acl: Access control list (private, public-read, public-read-write)
        location: Storage location/region
        versioning: Enable versioning
        encryption: Enable server-side encryption
        tags: Resource tags

    Example:
        # Create bucket on any provider
        bucket = UnifiedBucket(
            name="my-data-bucket",
            provider="gcp",
            acl="private",
            location="us-central1"
        )
        bucket.create()

        # Works identically on AWS, Azure, etc.
        aws_bucket = UnifiedBucket(
            name="my-data-bucket",
            provider="aws",
            acl="private"
        )
        aws_bucket.create()
    """

    resource_type: str = "UnifiedBucket"
    resource_type_list: List[str] = ["bucket", "container", "storage"]

    # Bucket configuration
    acl: Optional[str] = "private"  # Access control: private, public-read, public-read-write
    location: Optional[str] = None  # Storage location/region
    versioning: bool = False  # Enable versioning
    encryption: bool = False  # Enable server-side encryption
    tags: Optional[Dict[str, str]] = None  # Resource tags

    # Cached storage driver
    storage_driver: Optional[StorageDriver] = None

    def get_storage_driver(self) -> Optional[StorageDriver]:
        """Get or create storage driver for this provider."""
        if self.storage_driver is not None:
            return self.storage_driver

        # Get driver using provider factory with storage type
        driver = self.get_libcloud_driver(driver_type="storage")
        if driver:
            self.storage_driver = driver
        return self.storage_driver

    def _read(self, driver: StorageDriver) -> Optional[Container]:
        """Read bucket from cloud storage."""
        logger.debug(f"Reading bucket: {self.name}")

        try:
            # Get container by name
            container = driver.get_container(container_name=self.name)
            logger.info(f"Found bucket: {container.name}")
            self.active_resource = container
            return container

        except ContainerDoesNotExistError:
            logger.debug(f"Bucket {self.name} not found")
            return None
        except Exception as e:
            logger.error(f"Failed to read bucket: {e}")
            return None

    def _create(self, driver: StorageDriver) -> bool:
        """Create bucket on cloud storage."""
        print_info(f"Creating {self.get_resource_type()}: {self.name}")

        try:
            # Create container
            container = driver.create_container(container_name=self.name)

            if container:
                logger.info(f"Bucket created: {container.name}")
                self.active_resource = container
                return True
            else:
                logger.error("Failed to create bucket: no container returned")
                return False

        except Exception as e:
            logger.error(f"Failed to create bucket: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return False

    def _update(self, driver: StorageDriver) -> bool:
        """Update bucket configuration."""
        logger.warning("Bucket update operations are limited in Libcloud")
        # Most providers don't support container updates via Libcloud
        # For advanced features, use native SDK
        return True

    def _delete(self, driver: StorageDriver) -> bool:
        """Delete bucket from cloud storage."""
        print_info(f"Deleting {self.get_resource_type()}: {self.name}")

        try:
            # Get container
            container = self.active_resource or self._read(driver)

            if not container:
                logger.error(f"Bucket {self.name} not found")
                return False

            # Delete container
            result = driver.delete_container(container)

            if result:
                logger.info(f"Bucket deleted: {self.name}")
                self.active_resource = None
                return True
            else:
                logger.error("Failed to delete bucket")
                return False

        except Exception as e:
            logger.error(f"Failed to delete bucket: {e}")
            return False

    def read(self, client: Any = None) -> Any:
        """Read bucket using storage driver."""
        if self.use_cache and self.active_resource is not None:
            return self.active_resource

        if self.skip_read:
            print_info(f"Skipping read: {self.name}")
            return True

        driver = client or self.get_storage_driver()
        if driver is None:
            logger.error(f"Failed to get storage driver for {self.name}")
            return None

        return self._read(driver)

    def create(self, client: Any = None) -> bool:
        """Create bucket using storage driver."""
        if self.skip_create:
            print_info(f"Skipping create: {self.name}")
            return True

        driver = client or self.get_storage_driver()
        if driver is None:
            logger.error(f"Failed to get storage driver for {self.name}")
            return False

        # Check if already exists
        if self.use_cache and self.is_active(driver):
            self.resource_created = True
            print_info(f"{self.get_resource_type()}: {self.name} already exists")
        else:
            self.resource_created = self._create(driver)
            if self.resource_created:
                print_info(f"{self.get_resource_type()}: {self.name} created")

        if self.resource_created:
            if self.save_output:
                self.save_output_file()
            return self.post_create(driver)

        logger.error(f"Failed to create {self.get_resource_type()}: {self.name}")
        return False

    def delete(self, client: Any = None) -> bool:
        """Delete bucket using storage driver."""
        if self.skip_delete:
            print_info(f"Skipping delete: {self.name}")
            return True

        driver = client or self.get_storage_driver()
        if driver is None:
            logger.error(f"Failed to get storage driver for {self.name}")
            return False

        if not self.is_active(driver):
            print_info(f"{self.get_resource_type()}: {self.name} does not exist")
            return True

        self.resource_deleted = self._delete(driver)

        if self.resource_deleted:
            print_info(f"{self.get_resource_type()}: {self.name} deleted")
            if self.save_output:
                self.delete_output_file()
            return self.post_delete(driver)

        logger.error(f"Failed to delete {self.get_resource_type()}: {self.name}")
        return False

    def is_active(self, client: Any = None) -> bool:
        """Check if bucket exists."""
        resource = self.read(client)
        return resource is not None

    def list_objects(self, prefix: Optional[str] = None) -> List[Object]:
        """List objects in the bucket."""
        driver = self.get_storage_driver()
        container = self.active_resource or self._read(driver)

        if not container:
            logger.error(f"Bucket {self.name} not found")
            return []

        try:
            objects = driver.list_container_objects(container)

            if prefix:
                objects = [obj for obj in objects if obj.name.startswith(prefix)]

            return objects

        except Exception as e:
            logger.error(f"Failed to list objects: {e}")
            return []

    def get_size(self) -> int:
        """Get total size of objects in bucket (bytes)."""
        objects = self.list_objects()
        return sum(obj.size for obj in objects)

    def get_object_count(self) -> int:
        """Get number of objects in bucket."""
        return len(self.list_objects())


class UnifiedObject(UnifiedResource):
    """
    Unified object resource for cloud storage.

    This provides S3-compatible object management across all storage providers.

    Attributes:
        bucket_name: Name of the bucket/container
        object_key: Key/path of the object
        content: Object content (for uploads)
        local_path: Local file path (for uploads/downloads)
        content_type: MIME type of the object
        metadata: Object metadata

    Example:
        # Upload file to any provider
        obj = UnifiedObject(
            name="my-file.txt",
            bucket_name="my-bucket",
            object_key="data/my-file.txt",
            provider="aws",
            local_path="/path/to/file.txt"
        )
        obj.upload()

        # Download file
        obj.download("/path/to/download.txt")
    """

    resource_type: str = "UnifiedObject"
    resource_type_list: List[str] = ["object", "file", "blob"]

    # Object configuration
    bucket_name: str  # Required: bucket/container name
    object_key: Optional[str] = None  # Object key/path (defaults to name)
    content: Optional[Union[str, bytes]] = None  # Object content
    local_path: Optional[str] = None  # Local file path
    content_type: Optional[str] = None  # MIME type
    metadata: Optional[Dict[str, str]] = None  # Object metadata

    # Cached storage driver
    storage_driver: Optional[StorageDriver] = None

    def __init__(self, **data):
        """Initialize object with default object_key."""
        super().__init__(**data)
        if self.object_key is None:
            self.object_key = self.name

    def get_storage_driver(self) -> Optional[StorageDriver]:
        """Get or create storage driver for this provider."""
        if self.storage_driver is not None:
            return self.storage_driver

        driver = self.get_libcloud_driver(driver_type="storage")
        if driver:
            self.storage_driver = driver
        return self.storage_driver

    def _read(self, driver: StorageDriver) -> Optional[Object]:
        """Read object from cloud storage."""
        logger.debug(f"Reading object: {self.object_key} from {self.bucket_name}")

        try:
            container = driver.get_container(self.bucket_name)
            obj = driver.get_object(container_name=container.name, object_name=self.object_key)

            logger.info(f"Found object: {obj.name} (Size: {obj.size} bytes)")
            self.active_resource = obj
            return obj

        except (ContainerDoesNotExistError, ObjectDoesNotExistError):
            logger.debug(f"Object {self.object_key} not found")
            return None
        except Exception as e:
            logger.error(f"Failed to read object: {e}")
            return None

    def _create(self, driver: StorageDriver) -> bool:
        """Upload object to cloud storage."""
        return self.upload()

    def _delete(self, driver: StorageDriver) -> bool:
        """Delete object from cloud storage."""
        print_info(f"Deleting object: {self.object_key} from {self.bucket_name}")

        try:
            obj = self.active_resource or self._read(driver)

            if not obj:
                logger.error(f"Object {self.object_key} not found")
                return False

            result = driver.delete_object(obj)

            if result:
                logger.info(f"Object deleted: {self.object_key}")
                self.active_resource = None
                return True
            else:
                logger.error("Failed to delete object")
                return False

        except Exception as e:
            logger.error(f"Failed to delete object: {e}")
            return False

    def upload(self) -> bool:
        """Upload object from local file or content."""
        driver = self.get_storage_driver()
        if not driver:
            return False

        print_info(f"Uploading object: {self.object_key} to {self.bucket_name}")

        try:
            container = driver.get_container(self.bucket_name)

            # Upload from file
            if self.local_path:
                obj = driver.upload_object(
                    file_path=self.local_path,
                    container=container,
                    object_name=self.object_key,
                    extra={"content_type": self.content_type, "meta_data": self.metadata} if self.content_type or self.metadata else None,
                )
            # Upload from content
            elif self.content:
                import tempfile

                # Write content to temp file
                with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                    if isinstance(self.content, str):
                        temp_file.write(self.content.encode())
                    else:
                        temp_file.write(self.content)
                    temp_path = temp_file.name

                obj = driver.upload_object(
                    file_path=temp_path,
                    container=container,
                    object_name=self.object_key,
                    extra={"content_type": self.content_type, "meta_data": self.metadata} if self.content_type or self.metadata else None,
                )

                # Cleanup temp file
                import os

                os.unlink(temp_path)
            else:
                logger.error("No content or local_path provided for upload")
                return False

            if obj:
                logger.info(f"Object uploaded: {obj.name} (Size: {obj.size} bytes)")
                self.active_resource = obj
                return True
            else:
                logger.error("Failed to upload object")
                return False

        except Exception as e:
            logger.error(f"Failed to upload object: {e}")
            import traceback

            logger.debug(traceback.format_exc())
            return False

    def download(self, destination_path: str) -> bool:
        """Download object to local file."""
        driver = self.get_storage_driver()
        if not driver:
            return False

        print_info(f"Downloading object: {self.object_key} from {self.bucket_name}")

        try:
            obj = self.active_resource or self._read(driver)

            if not obj:
                logger.error(f"Object {self.object_key} not found")
                return False

            driver.download_object(obj, destination_path, overwrite_existing=True)

            logger.info(f"Object downloaded to: {destination_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download object: {e}")
            return False

    def get_download_url(self, expires_in: int = 3600) -> Optional[str]:
        """Get pre-signed download URL for object."""
        driver = self.get_storage_driver()
        if not driver:
            return None

        try:
            obj = self.active_resource or self._read(driver)

            if not obj:
                logger.error(f"Object {self.object_key} not found")
                return None

            # Get download URL (may not be supported by all providers)
            url = driver.get_object_cdn_url(obj)
            return url

        except Exception as e:
            logger.warning(f"Failed to get download URL: {e}")
            return None

    def get_content(self) -> Optional[bytes]:
        """Download and return object content."""
        driver = self.get_storage_driver()
        if not driver:
            return None

        try:
            obj = self.active_resource or self._read(driver)

            if not obj:
                logger.error(f"Object {self.object_key} not found")
                return None

            # Download to memory
            import io

            stream = io.BytesIO()
            for chunk in driver.download_object_as_stream(obj):
                stream.write(chunk)

            return stream.getvalue()

        except Exception as e:
            logger.error(f"Failed to get object content: {e}")
            return None
