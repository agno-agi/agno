"""GCS content loader for Knowledge.

Provides methods for loading content from Google Cloud Storage.
"""

from io import BytesIO
from typing import Optional, cast

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import RemoteContentLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import GcsConfig, RemoteContentConfig
from agno.knowledge.remote_content.remote_content import GCSContent
from agno.utils.log import log_warning
from agno.utils.string import generate_id


class GCSLoader(RemoteContentLoader):
    """Loader for Google Cloud Storage content."""

    async def _aload_from_gcs(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load the contextual GCS content.

        Note: Uses sync google-cloud-storage calls as it doesn't have an async API.

        1. Identify objects to read
        2. Setup Content object
        3. Hash content and add it to the contents database
        4. Select reader
        5. Fetch and load the content
        6. Read the content
        7. Prepare and insert the content in the vector database
        """
        try:
            from google.cloud import storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        # Note: GCS support has limited features compared to GitHub/SharePoint
        log_warning(
            "GCS content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: GCSContent = cast(GCSContent, content.remote_content)

        # Get or create bucket with credentials from config
        bucket = remote_content.bucket
        if bucket is None and remote_content.bucket_name:
            gcs_config = cast(GcsConfig, config) if isinstance(config, GcsConfig) else None
            if gcs_config and gcs_config.credentials_path:
                client = storage.Client.from_service_account_json(gcs_config.credentials_path)
            elif gcs_config and gcs_config.project:
                client = storage.Client(project=gcs_config.project)
            else:
                client = storage.Client()
            bucket = client.bucket(remote_content.bucket_name)

        # 1. Identify objects to read
        objects_to_read = []
        if remote_content.blob_name is not None:
            objects_to_read.append(bucket.blob(remote_content.blob_name))  # type: ignore
        elif remote_content.prefix is not None:
            objects_to_read.extend(bucket.list_blobs(prefix=remote_content.prefix))  # type: ignore
        else:
            objects_to_read.extend(bucket.list_blobs())  # type: ignore

        for gcs_object in objects_to_read:
            # 2. Setup Content object
            name = (content.name or "content") + "_" + gcs_object.name
            content_entry = Content(
                name=name,
                description=content.description,
                status=ContentStatus.PROCESSING,
                metadata=content.metadata,
                file_type="gcs",
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
            reader = self._select_reader_by_uri(gcs_object.name, content.reader)
            reader = cast(Reader, reader)

            # 5. Fetch and load the content
            readable_content = BytesIO(gcs_object.download_as_bytes())

            # 6. Read the content
            read_documents = await reader.async_read(readable_content, name=name)

            # 7. Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_gcs(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Synchronous version of _load_from_gcs.

        Load the contextual GCS content:
        1. Identify objects to read
        2. Setup Content object
        3. Hash content and add it to the contents database
        4. Select reader
        5. Fetch and load the content
        6. Read the content
        7. Prepare and insert the content in the vector database
        """
        try:
            from google.cloud import storage  # type: ignore
        except ImportError:
            raise ImportError(
                "The `google-cloud-storage` package is not installed. "
                "Please install it via `pip install google-cloud-storage`."
            )

        # Note: GCS support has limited features compared to GitHub/SharePoint
        log_warning(
            "GCS content loading has limited features. "
            "Recursive folder traversal, rich metadata, and improved naming are coming in a future release."
        )

        remote_content: GCSContent = cast(GCSContent, content.remote_content)

        # Get or create bucket with credentials from config
        bucket = remote_content.bucket
        if bucket is None and remote_content.bucket_name:
            gcs_config = cast(GcsConfig, config) if isinstance(config, GcsConfig) else None
            if gcs_config and gcs_config.credentials_path:
                client = storage.Client.from_service_account_json(gcs_config.credentials_path)
            elif gcs_config and gcs_config.project:
                client = storage.Client(project=gcs_config.project)
            else:
                client = storage.Client()
            bucket = client.bucket(remote_content.bucket_name)

        # 1. Identify objects to read
        objects_to_read = []
        if remote_content.blob_name is not None:
            objects_to_read.append(bucket.blob(remote_content.blob_name))  # type: ignore
        elif remote_content.prefix is not None:
            objects_to_read.extend(bucket.list_blobs(prefix=remote_content.prefix))  # type: ignore
        else:
            objects_to_read.extend(bucket.list_blobs())  # type: ignore

        for gcs_object in objects_to_read:
            # 2. Setup Content object
            name = (content.name or "content") + "_" + gcs_object.name
            content_entry = Content(
                name=name,
                description=content.description,
                status=ContentStatus.PROCESSING,
                metadata=content.metadata,
                file_type="gcs",
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
            reader = self._select_reader_by_uri(gcs_object.name, content.reader)
            reader = cast(Reader, reader)

            # 5. Fetch and load the content
            readable_content = BytesIO(gcs_object.download_as_bytes())

            # 6. Read the content
            read_documents = reader.read(readable_content, name=name)

            # 7. Prepare and insert the content in the vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            self._handle_vector_db_insert(content_entry, read_documents, upsert)
