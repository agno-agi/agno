"""GCS content loader for Knowledge.

Provides methods for loading content from Google Cloud Storage.
"""

# mypy: disable-error-code="attr-defined"

from io import BytesIO
from typing import Any, Dict, Optional, cast

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import BaseStorageConfig, GcsConfig
from agno.knowledge.remote_content.remote_content import GCSContent
from agno.utils.log import log_info, log_warning
from agno.utils.string import generate_id


class GCSLoader(BaseLoader):
    """Loader for Google Cloud Storage content."""

    # ==========================================
    # GCS HELPERS (shared between sync/async)
    # ==========================================

    def _validate_gcs_config(
        self,
        content: Content,
        config: Optional[BaseStorageConfig],
    ) -> Optional[GcsConfig]:
        """Validate and extract GCS config.

        Returns:
            GcsConfig if valid, None otherwise (GCS can work without explicit config)
        """
        return cast(GcsConfig, config) if isinstance(config, GcsConfig) else None

    def _get_gcs_client(self, gcs_config: Optional[GcsConfig]):
        """Get a GCS client.

        Requires the `google-cloud-storage` package.
        """
        try:
            from google.cloud import storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        if gcs_config and gcs_config.credentials_path:
            return storage.Client.from_service_account_json(gcs_config.credentials_path)
        elif gcs_config and gcs_config.project:
            return storage.Client(project=gcs_config.project)
        else:
            return storage.Client()

    def _build_gcs_metadata(
        self,
        gcs_config: Optional[GcsConfig],
        bucket_name: str,
        blob_name: str,
    ) -> Dict[str, str]:
        """Build GCS-specific metadata dictionary."""
        metadata: Dict[str, str] = {
            "source_type": "gcs",
            "gcs_bucket": bucket_name,
            "gcs_blob_name": blob_name,
        }
        if gcs_config:
            metadata["source_config_id"] = gcs_config.id
            metadata["source_config_name"] = gcs_config.name
        return metadata

    def _build_gcs_virtual_path(self, bucket_name: str, blob_name: str) -> str:
        """Build virtual path for GCS content."""
        return f"gcs://{bucket_name}/{blob_name}"

    # ==========================================
    # GCS LOADERS
    # ==========================================

    async def _aload_from_gcs(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[BaseStorageConfig] = None,
        backup: Optional[bool] = None,
    ):
        """Load content from Google Cloud Storage (async).

        Note: Uses sync google-cloud-storage calls as it doesn't have an async API.
        """
        try:
            from google.cloud import storage  # type: ignore  # noqa: F401
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        log_warning(
            "GCS content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: GCSContent = cast(GCSContent, content.remote_content)
        gcs_config = self._validate_gcs_config(content, config)

        # Get or create bucket
        bucket = remote_content.bucket
        if bucket is None and remote_content.bucket_name:
            client = self._get_gcs_client(gcs_config)
            bucket = client.bucket(remote_content.bucket_name)

        # Identify objects to read
        objects_to_read = []
        if remote_content.blob_name is not None:
            objects_to_read.append(bucket.blob(remote_content.blob_name))  # type: ignore
        elif remote_content.prefix is not None:
            objects_to_read.extend(bucket.list_blobs(prefix=remote_content.prefix))  # type: ignore
        else:
            objects_to_read.extend(bucket.list_blobs())  # type: ignore

        if objects_to_read:
            log_info(f"Processing {len(objects_to_read)} file(s) from GCS")

        bucket_name = remote_content.bucket_name or (bucket.name if bucket else "unknown")
        is_folder_upload = len(objects_to_read) > 1
        root_path = remote_content.prefix or ""

        for gcs_object in objects_to_read:
            blob_name = gcs_object.name
            file_name = blob_name.split("/")[-1]

            # Build metadata and virtual path using helpers
            virtual_path = self._build_gcs_virtual_path(bucket_name, blob_name)
            gcs_metadata = self._build_gcs_metadata(gcs_config, bucket_name, blob_name)
            merged_metadata: Dict[str, Any] = self._merge_metadata(gcs_metadata, content.metadata)

            # Compute content name using base helper
            content_name = self._compute_content_name(blob_name, file_name, content.name, root_path, is_folder_upload)

            # Create content entry
            content_entry = Content(
                name=content_name,
                description=content.description,
                path=virtual_path,
                status=ContentStatus.PROCESSING,
                metadata=merged_metadata,
                file_type="gcs",
            )
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)

            await self._ainsert_contents_db(content_entry)

            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                await self._aupdate_content(content_entry)
                continue

            # Select reader
            reader = self._select_reader_by_uri(gcs_object.name, content.reader)
            reader = cast(Reader, reader)

            # Fetch the content bytes
            file_bytes = gcs_object.download_as_bytes()
            readable_content = BytesIO(file_bytes)

            # Store backup copy if configured
            await self._abackup_bytes(content_entry, file_bytes, file_name, backup)

            # Read the content
            read_documents = await reader.async_read(readable_content, name=file_name)

            # Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_gcs(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[BaseStorageConfig] = None,
        backup: Optional[bool] = None,
    ):
        """Load content from Google Cloud Storage (sync)."""
        try:
            from google.cloud import storage  # type: ignore  # noqa: F401
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        log_warning(
            "GCS content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: GCSContent = cast(GCSContent, content.remote_content)
        gcs_config = self._validate_gcs_config(content, config)

        # Get or create bucket
        bucket = remote_content.bucket
        if bucket is None and remote_content.bucket_name:
            client = self._get_gcs_client(gcs_config)
            bucket = client.bucket(remote_content.bucket_name)

        # Identify objects to read
        objects_to_read = []
        if remote_content.blob_name is not None:
            objects_to_read.append(bucket.blob(remote_content.blob_name))  # type: ignore
        elif remote_content.prefix is not None:
            objects_to_read.extend(bucket.list_blobs(prefix=remote_content.prefix))  # type: ignore
        else:
            objects_to_read.extend(bucket.list_blobs())  # type: ignore

        if objects_to_read:
            log_info(f"Processing {len(objects_to_read)} file(s) from GCS")

        bucket_name = remote_content.bucket_name or (bucket.name if bucket else "unknown")
        is_folder_upload = len(objects_to_read) > 1
        root_path = remote_content.prefix or ""

        for gcs_object in objects_to_read:
            blob_name = gcs_object.name
            file_name = blob_name.split("/")[-1]

            # Build metadata and virtual path using helpers
            virtual_path = self._build_gcs_virtual_path(bucket_name, blob_name)
            gcs_metadata = self._build_gcs_metadata(gcs_config, bucket_name, blob_name)
            merged_metadata: Dict[str, Any] = self._merge_metadata(gcs_metadata, content.metadata)

            # Compute content name using base helper
            content_name = self._compute_content_name(blob_name, file_name, content.name, root_path, is_folder_upload)

            # Create content entry
            content_entry = Content(
                name=content_name,
                description=content.description,
                path=virtual_path,
                status=ContentStatus.PROCESSING,
                metadata=merged_metadata,
                file_type="gcs",
            )
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)

            self._insert_contents_db(content_entry)

            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                self._update_content(content_entry)
                continue

            # Select reader
            reader = self._select_reader_by_uri(gcs_object.name, content.reader)
            reader = cast(Reader, reader)

            # Fetch the content bytes
            file_bytes = gcs_object.download_as_bytes()
            readable_content = BytesIO(file_bytes)

            # Store backup copy if configured
            self._backup_bytes(content_entry, file_bytes, file_name, backup)

            # Read the content
            read_documents = reader.read(readable_content, name=file_name)

            # Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            self._handle_vector_db_insert(content_entry, read_documents, upsert)
