"""S3 content loader for Knowledge.

Provides methods for loading content from AWS S3.
"""

# mypy: disable-error-code="attr-defined"

from io import BytesIO
from pathlib import Path
from typing import List, Optional, Union, cast

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import RemoteContentConfig, S3Config
from agno.knowledge.remote_content.remote_content import S3Content
from agno.utils.log import log_error, log_warning
from agno.utils.string import generate_id


class S3Loader:
    """Loader for S3 content."""

    async def _aload_from_s3(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load the contextual S3 content.

        Note: Uses sync boto3 calls as boto3 doesn't have an async API.

        1. Identify objects to read
        2. Setup Content object
        3. Hash content and add it to the contents database
        4. Select reader
        5. Fetch and load the content
        6. Read the content
        7. Prepare and insert the content in the vector database
        8. Remove temporary file if needed
        """
        from agno.cloud.aws.s3.bucket import S3Bucket
        from agno.cloud.aws.s3.object import S3Object

        # Note: S3 support has limited features compared to GitHub/SharePoint
        log_warning(
            "S3 content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: S3Content = cast(S3Content, content.remote_content)

        # Get or create bucket with credentials from config
        bucket = remote_content.bucket
        try:
            if bucket is None and remote_content.bucket_name:
                s3_config = cast(S3Config, config) if isinstance(config, S3Config) else None
                bucket = S3Bucket(
                    name=remote_content.bucket_name,
                    region=s3_config.region if s3_config else None,
                    aws_access_key_id=s3_config.aws_access_key_id if s3_config else None,
                    aws_secret_access_key=s3_config.aws_secret_access_key if s3_config else None,
                )
        except Exception as e:
            log_error(f"Error getting bucket: {e}")

        # 1. Identify objects to read
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

        for s3_object in objects_to_read:
            # 2. Setup Content object
            content_name = content.name or ""
            content_name += "_" + (s3_object.name or "")
            content_entry = Content(
                name=content_name,
                description=content.description,
                status=ContentStatus.PROCESSING,
                metadata=content.metadata,
                file_type="s3",
            )

            # 3. Hash content and add it to the contents database
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)
            await self._ainsert_contents_db(content_entry)
            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                await self._aupdate_content(content_entry)
                continue

            # 4. Select reader
            reader = self._select_reader_by_uri(s3_object.uri, content.reader)
            reader = cast(Reader, reader)

            # 5. Fetch and load the content
            temporary_file = None
            obj_name = content_name or s3_object.name.split("/")[-1]
            readable_content: Optional[Union[BytesIO, Path]] = None
            if s3_object.uri.endswith(".pdf"):
                readable_content = BytesIO(s3_object.get_resource().get()["Body"].read())
            else:
                temporary_file = Path("storage").joinpath(obj_name)
                readable_content = temporary_file
                s3_object.download(readable_content)  # type: ignore

            # 6. Read the content
            read_documents = await reader.async_read(readable_content, name=obj_name)

            # 7. Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

            # 8. Remove temporary file if needed
            if temporary_file:
                temporary_file.unlink()

    def _load_from_s3(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Synchronous version of _load_from_s3.

        Load the contextual S3 content:
        1. Identify objects to read
        2. Setup Content object
        3. Hash content and add it to the contents database
        4. Select reader
        5. Fetch and load the content
        6. Read the content
        7. Prepare and insert the content in the vector database
        8. Remove temporary file if needed
        """
        from agno.cloud.aws.s3.bucket import S3Bucket
        from agno.cloud.aws.s3.object import S3Object

        # Note: S3 support has limited features compared to GitHub/SharePoint
        log_warning(
            "S3 content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: S3Content = cast(S3Content, content.remote_content)

        # Get or create bucket with credentials from config
        bucket = remote_content.bucket
        if bucket is None and remote_content.bucket_name:
            s3_config = cast(S3Config, config) if isinstance(config, S3Config) else None
            bucket = S3Bucket(
                name=remote_content.bucket_name,
                region=s3_config.region if s3_config else None,
                aws_access_key_id=s3_config.aws_access_key_id if s3_config else None,
                aws_secret_access_key=s3_config.aws_secret_access_key if s3_config else None,
            )

        # 1. Identify objects to read
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

        for s3_object in objects_to_read:
            # 2. Setup Content object
            content_name = content.name or ""
            content_name += "_" + (s3_object.name or "")
            content_entry = Content(
                name=content_name,
                description=content.description,
                status=ContentStatus.PROCESSING,
                metadata=content.metadata,
                file_type="s3",
            )

            # 3. Hash content and add it to the contents database
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)
            self._insert_contents_db(content_entry)
            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                self._update_content(content_entry)
                continue

            # 4. Select reader
            reader = self._select_reader_by_uri(s3_object.uri, content.reader)
            reader = cast(Reader, reader)

            # 5. Fetch and load the content
            temporary_file = None
            obj_name = content_name or s3_object.name.split("/")[-1]
            readable_content: Optional[Union[BytesIO, Path]] = None
            if s3_object.uri.endswith(".pdf"):
                readable_content = BytesIO(s3_object.get_resource().get()["Body"].read())
            else:
                temporary_file = Path("storage").joinpath(obj_name)
                readable_content = temporary_file
                s3_object.download(readable_content)  # type: ignore

            # 6. Read the content
            read_documents = reader.read(readable_content, name=obj_name)

            # 7. Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            self._handle_vector_db_insert(content_entry, read_documents, upsert)

            # 8. Remove temporary file if needed
            if temporary_file:
                temporary_file.unlink()
