"""S3 content loader for Knowledge.

Provides methods for loading content from AWS S3.
"""

# mypy: disable-error-code="attr-defined"

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import RemoteContentConfig, S3Config
from agno.knowledge.remote_content.remote_content import S3Content
from agno.utils.log import log_error, log_info, log_warning
from agno.utils.string import generate_id


class S3Loader(BaseLoader):
    """Loader for S3 content."""

    # ==========================================
    # S3 HELPERS (shared between sync/async)
    # ==========================================

    def _validate_s3_config(
        self,
        content: Content,
        config: Optional[RemoteContentConfig],
    ) -> Optional[S3Config]:
        """Validate and extract S3 config.

        Returns:
            S3Config if valid, None otherwise (S3 can work without explicit config)
        """
        return cast(S3Config, config) if isinstance(config, S3Config) else None

    def _build_s3_metadata(
        self,
        s3_config: Optional[S3Config],
        bucket_name: str,
        object_name: str,
    ) -> Dict[str, str]:
        """Build S3-specific metadata dictionary."""
        metadata: Dict[str, str] = {
            "source_type": "s3",
            "s3_bucket": bucket_name,
            "s3_object_name": object_name,
        }
        if s3_config:
            metadata["source_config_id"] = s3_config.id
            metadata["source_config_name"] = s3_config.name
            if s3_config.region:
                metadata["s3_region"] = s3_config.region
        return metadata

    def _build_s3_virtual_path(self, bucket_name: str, object_name: str) -> str:
        """Build virtual path for S3 content."""
        return f"s3://{bucket_name}/{object_name}"

    # ==========================================
    # S3 LOADERS
    # ==========================================

    async def _aload_from_s3(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from AWS S3 (async).

        Note: Uses sync boto3 calls as boto3 doesn't have an async API.
        """
        from agno.cloud.aws.s3.bucket import S3Bucket
        from agno.cloud.aws.s3.object import S3Object

        log_warning(
            "S3 content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: S3Content = cast(S3Content, content.remote_content)
        s3_config = self._validate_s3_config(content, config)

        # Get or create bucket with credentials from config
        bucket = remote_content.bucket
        try:
            if bucket is None and remote_content.bucket_name:
                bucket = S3Bucket(
                    name=remote_content.bucket_name,
                    region=s3_config.region if s3_config else None,
                    aws_access_key_id=s3_config.aws_access_key_id if s3_config else None,
                    aws_secret_access_key=s3_config.aws_secret_access_key if s3_config else None,
                )
        except Exception as e:
            log_error(f"Error getting bucket: {e}")

        # Identify objects to read
        objects_to_read: List[S3Object] = []
        if bucket is not None:
            if remote_content.key is not None:
                _object = S3Object(bucket_name=bucket.name, name=remote_content.key)
                objects_to_read.append(_object)
            elif remote_content.object is not None:
                objects_to_read.append(remote_content.object)
            elif remote_content.prefix is not None:
                objects_to_read.extend(bucket.get_objects(prefix=remote_content.prefix))
            else:
                objects_to_read.extend(bucket.get_objects())

        if objects_to_read:
            log_info(f"Processing {len(objects_to_read)} file(s) from S3")

        bucket_name = bucket.name if bucket else "unknown"
        is_folder_upload = len(objects_to_read) > 1
        root_path = remote_content.prefix or ""

        for s3_object in objects_to_read:
            object_name = s3_object.name or ""
            file_name = object_name.split("/")[-1]

            # Build metadata and virtual path using helpers
            virtual_path = self._build_s3_virtual_path(bucket_name, object_name)
            s3_metadata = self._build_s3_metadata(s3_config, bucket_name, object_name)
            merged_metadata: Dict[str, Any] = self._merge_metadata(s3_metadata, content.metadata)

            # Compute content name using base helper
            content_name = self._compute_content_name(object_name, file_name, content.name, root_path, is_folder_upload)

            # Create content entry
            content_entry = Content(
                name=content_name,
                description=content.description,
                path=virtual_path,
                status=ContentStatus.PROCESSING,
                metadata=merged_metadata,
                file_type="s3",
            )
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)

            await self._ainsert_contents_db(content_entry)

            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                await self._aupdate_content(content_entry)
                continue

            # Select reader
            reader = self._select_reader_by_uri(s3_object.uri, content.reader)
            reader = cast(Reader, reader)

            # Fetch and load the content
            temporary_file = None
            readable_content: Optional[Union[BytesIO, Path]] = None
            if s3_object.uri.endswith(".pdf"):
                readable_content = BytesIO(s3_object.get_resource().get()["Body"].read())
            else:
                temporary_file = Path("storage").joinpath(file_name)
                readable_content = temporary_file
                s3_object.download(readable_content)  # type: ignore

            # Read the content
            read_documents = await reader.async_read(readable_content, name=file_name)

            # Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

            # Remove temporary file if needed
            if temporary_file:
                temporary_file.unlink()

    def _load_from_s3(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from AWS S3 (sync)."""
        from agno.cloud.aws.s3.bucket import S3Bucket
        from agno.cloud.aws.s3.object import S3Object

        log_warning(
            "S3 content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: S3Content = cast(S3Content, content.remote_content)
        s3_config = self._validate_s3_config(content, config)

        # Get or create bucket with credentials from config
        bucket = remote_content.bucket
        if bucket is None and remote_content.bucket_name:
            bucket = S3Bucket(
                name=remote_content.bucket_name,
                region=s3_config.region if s3_config else None,
                aws_access_key_id=s3_config.aws_access_key_id if s3_config else None,
                aws_secret_access_key=s3_config.aws_secret_access_key if s3_config else None,
            )

        # Identify objects to read
        objects_to_read: List[S3Object] = []
        if bucket is not None:
            if remote_content.key is not None:
                _object = S3Object(bucket_name=bucket.name, name=remote_content.key)
                objects_to_read.append(_object)
            elif remote_content.object is not None:
                objects_to_read.append(remote_content.object)
            elif remote_content.prefix is not None:
                objects_to_read.extend(bucket.get_objects(prefix=remote_content.prefix))
            else:
                objects_to_read.extend(bucket.get_objects())

        if objects_to_read:
            log_info(f"Processing {len(objects_to_read)} file(s) from S3")

        bucket_name = bucket.name if bucket else "unknown"
        is_folder_upload = len(objects_to_read) > 1
        root_path = remote_content.prefix or ""

        for s3_object in objects_to_read:
            object_name = s3_object.name or ""
            file_name = object_name.split("/")[-1]

            # Build metadata and virtual path using helpers
            virtual_path = self._build_s3_virtual_path(bucket_name, object_name)
            s3_metadata = self._build_s3_metadata(s3_config, bucket_name, object_name)
            merged_metadata: Dict[str, Any] = self._merge_metadata(s3_metadata, content.metadata)

            # Compute content name using base helper
            content_name = self._compute_content_name(object_name, file_name, content.name, root_path, is_folder_upload)

            # Create content entry
            content_entry = Content(
                name=content_name,
                description=content.description,
                path=virtual_path,
                status=ContentStatus.PROCESSING,
                metadata=merged_metadata,
                file_type="s3",
            )
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)

            self._insert_contents_db(content_entry)

            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                self._update_content(content_entry)
                continue

            # Select reader
            reader = self._select_reader_by_uri(s3_object.uri, content.reader)
            reader = cast(Reader, reader)

            # Fetch and load the content
            temporary_file = None
            readable_content: Optional[Union[BytesIO, Path]] = None
            if s3_object.uri.endswith(".pdf"):
                readable_content = BytesIO(s3_object.get_resource().get()["Body"].read())
            else:
                temporary_file = Path("storage").joinpath(file_name)
                readable_content = temporary_file
                s3_object.download(readable_content)  # type: ignore

            # Read the content
            read_documents = reader.read(readable_content, name=file_name)

            # Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            self._handle_vector_db_insert(content_entry, read_documents, upsert)

            # Remove temporary file if needed
            if temporary_file:
                temporary_file.unlink()
