"""Remote content loading for Knowledge.

Provides methods for loading content from cloud storage providers:
- S3, GCS, SharePoint, GitHub, Azure Blob Storage

This module contains the RemoteKnowledge base class which handles all remote
content loading operations. The Knowledge class inherits from this to gain
remote content capabilities.
"""

from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, cast

import httpx
from httpx import AsyncClient

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.config import (
    AzureBlobConfig,
    GcsConfig,
    GitHubConfig,
    RemoteContentConfig,
    S3Config,
    SharePointConfig,
)
from agno.knowledge.remote_content.remote_content import (
    AzureBlobContent,
    GCSContent,
    GitHubContent,
    S3Content,
    SharePointContent,
)
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.string import generate_id


class RemoteKnowledge:
    """Base class providing remote content loading capabilities.

    Knowledge inherits from this class and provides:
    - content_sources: List[RemoteContentConfig]
    - vector_db, contents_db attributes
    - _should_skip(), _select_reader_by_uri(), _prepare_documents_for_insert() methods
    - _ahandle_vector_db_insert(), _handle_vector_db_insert() methods
    - _ainsert_contents_db(), _insert_contents_db() methods
    - _aupdate_content(), _update_content() methods
    - _build_content_hash() method
    """

    # These attributes are provided by the Knowledge subclass
    content_sources: Optional[List[RemoteContentConfig]]

    # ==========================================
    # REMOTE CONTENT DISPATCHERS
    # ==========================================

    async def _aload_from_remote_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        if content.remote_content is None:
            log_warning("No remote content provided for content")
            return

        remote_content = content.remote_content

        # Look up config if config_id is provided
        config = None
        if hasattr(remote_content, "config_id") and remote_content.config_id:
            config = self._get_remote_config_by_id(remote_content.config_id)
            if config is None:
                log_warning(f"No config found for config_id: {remote_content.config_id}")

        if isinstance(remote_content, S3Content):
            await self._aload_from_s3(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GCSContent):
            await self._aload_from_gcs(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, SharePointContent):
            await self._aload_from_sharepoint(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GitHubContent):
            await self._aload_from_github(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, AzureBlobContent):
            await self._aload_from_azure_blob(content, upsert, skip_if_exists, config)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

    def _load_from_remote_content(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
    ):
        """Synchronous version of _load_from_remote_content."""
        if content.remote_content is None:
            log_warning("No remote content provided for content")
            return

        remote_content = content.remote_content

        # Look up config if config_id is provided
        config = None
        if hasattr(remote_content, "config_id") and remote_content.config_id:
            config = self._get_remote_config_by_id(remote_content.config_id)
            if config is None:
                log_warning(f"No config found for config_id: {remote_content.config_id}")

        if isinstance(remote_content, S3Content):
            self._load_from_s3(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GCSContent):
            self._load_from_gcs(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, SharePointContent):
            self._load_from_sharepoint(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, GitHubContent):
            self._load_from_github(content, upsert, skip_if_exists, config)

        elif isinstance(remote_content, AzureBlobContent):
            self._load_from_azure_blob(content, upsert, skip_if_exists, config)

        else:
            log_warning(f"Unsupported remote content type: {type(remote_content)}")

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

    # ==========================================
    # GCS LOADERS
    # ==========================================

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

    # ==========================================
    # SHAREPOINT HELPERS
    # ==========================================

    def _get_sharepoint_access_token(self, sp_config: SharePointConfig) -> Optional[str]:
        """Get an access token for Microsoft Graph API using client credentials flow.

        Requires the `msal` package: pip install msal
        """
        try:
            from msal import ConfidentialClientApplication  # type: ignore
        except ImportError:
            raise ImportError("The `msal` package is not installed. Please install it via `pip install msal`.")

        authority = f"https://login.microsoftonline.com/{sp_config.tenant_id}"
        app = ConfidentialClientApplication(
            sp_config.client_id,
            authority=authority,
            client_credential=sp_config.client_secret,
        )

        # Acquire token for Microsoft Graph
        scopes = ["https://graph.microsoft.com/.default"]
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:
            return result["access_token"]
        else:
            log_error(f"Failed to acquire SharePoint token: {result.get('error_description', result.get('error'))}")
            return None

    def _get_sharepoint_site_id(self, hostname: str, site_path: Optional[str], access_token: str) -> Optional[str]:
        """Get the SharePoint site ID using Microsoft Graph API."""
        import httpx

        if site_path:
            url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{site_path}"
        else:
            url = f"https://graph.microsoft.com/v1.0/sites/{hostname}"

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = httpx.get(url, headers=headers)
            response.raise_for_status()
            return response.json().get("id")
        except httpx.HTTPStatusError as e:
            log_error(f"Failed to get SharePoint site ID: {e.response.status_code} - {e.response.text}")
            return None

    def _list_sharepoint_folder_items(self, site_id: str, folder_path: str, access_token: str) -> List[dict]:
        """List all items in a SharePoint folder."""
        import httpx

        # Strip leading slashes to avoid double-slash in URL
        folder_path = folder_path.lstrip("/")
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{folder_path}:/children"
        headers = {"Authorization": f"Bearer {access_token}"}
        items: List[dict] = []

        try:
            while url:
                response = httpx.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                items.extend(data.get("value", []))
                url = data.get("@odata.nextLink")
        except httpx.HTTPStatusError as e:
            log_error(f"Failed to list SharePoint folder: {e.response.status_code} - {e.response.text}")

        return items

    def _download_sharepoint_file(self, site_id: str, file_path: str, access_token: str) -> Optional[BytesIO]:
        """Download a file from SharePoint."""
        import httpx

        # Strip leading slashes to avoid double-slash in URL
        file_path = file_path.lstrip("/")
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{file_path}:/content"
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = httpx.get(url, headers=headers, follow_redirects=True)
            response.raise_for_status()
            return BytesIO(response.content)
        except httpx.HTTPStatusError as e:
            log_error(f"Failed to download SharePoint file {file_path}: {e.response.status_code} - {e.response.text}")
            return None

    async def _aget_sharepoint_site_id(
        self, hostname: str, site_path: Optional[str], access_token: str
    ) -> Optional[str]:
        """Get the SharePoint site ID using Microsoft Graph API (async)."""
        import httpx

        if site_path:
            url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:/{site_path}"
        else:
            url = f"https://graph.microsoft.com/v1.0/sites/{hostname}"

        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json().get("id")
        except httpx.HTTPStatusError as e:
            log_error(f"Failed to get SharePoint site ID: {e.response.status_code} - {e.response.text}")
            return None

    async def _alist_sharepoint_folder_items(self, site_id: str, folder_path: str, access_token: str) -> List[dict]:
        """List all items in a SharePoint folder (async)."""
        import httpx

        # Strip leading slashes to avoid double-slash in URL
        folder_path = folder_path.lstrip("/")
        url: Optional[str] = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{folder_path}:/children"
        headers = {"Authorization": f"Bearer {access_token}"}
        items: List[dict] = []

        try:
            async with httpx.AsyncClient() as client:
                while url:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    items.extend(data.get("value", []))
                    url = data.get("@odata.nextLink")
        except httpx.HTTPStatusError as e:
            log_error(f"Failed to list SharePoint folder: {e.response.status_code} - {e.response.text}")

        return items

    async def _adownload_sharepoint_file(self, site_id: str, file_path: str, access_token: str) -> Optional[BytesIO]:
        """Download a file from SharePoint (async)."""
        import httpx

        # Strip leading slashes to avoid double-slash in URL
        file_path = file_path.lstrip("/")
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{file_path}:/content"
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, follow_redirects=True)
                response.raise_for_status()
                return BytesIO(response.content)
        except httpx.HTTPStatusError as e:
            log_error(f"Failed to download SharePoint file {file_path}: {e.response.status_code} - {e.response.text}")
            return None

    # ==========================================
    # SHAREPOINT LOADERS
    # ==========================================

    async def _aload_from_sharepoint(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from SharePoint.

        Requires the SharePoint config to contain tenant_id, client_id, client_secret, and hostname.

        1. Authenticate with Microsoft Graph using client credentials
        2. Get site ID from hostname/site_path
        3. Download file(s) from file_path or folder_path
        4. Process through reader and insert to vector db
        """
        remote_content: SharePointContent = cast(SharePointContent, content.remote_content)
        sp_config = cast(SharePointConfig, config) if isinstance(config, SharePointConfig) else None

        if sp_config is None:
            log_error(f"SharePoint config not found for config_id: {remote_content.config_id}")
            return

        # 1. Get access token
        access_token = self._get_sharepoint_access_token(sp_config)
        if not access_token:
            return

        # 2. Get site ID - use config value if provided, otherwise fetch via API
        site_id: Optional[str] = sp_config.site_id
        if not site_id:
            site_path = remote_content.site_path or sp_config.site_path
            site_id = await self._aget_sharepoint_site_id(sp_config.hostname, site_path, access_token)
            if not site_id:
                log_error(f"Failed to get SharePoint site ID for {sp_config.hostname}/{site_path}")
                return

        # 3. Identify files to download
        files_to_process: List[tuple] = []  # List of (file_path, file_name)

        # Helper function to recursively list all files in a folder
        async def list_files_recursive(folder: str) -> List[tuple]:
            """Recursively list all files in a SharePoint folder."""
            files: List[tuple] = []
            items = await self._alist_sharepoint_folder_items(site_id, folder, access_token)
            for item in items:
                if "file" in item:  # It's a file
                    item_path = f"{folder}/{item['name']}"
                    files.append((item_path, item["name"]))
                elif "folder" in item:  # It's a folder - recurse
                    subdir_path = f"{folder}/{item['name']}"
                    subdir_files = await list_files_recursive(subdir_path)
                    files.extend(subdir_files)
            return files

        # Get the path to process (file_path or folder_path)
        path_to_process = (remote_content.file_path or remote_content.folder_path or "").strip("/")

        if path_to_process:
            # Check if path is a file or folder by getting item metadata
            try:
                async with AsyncClient() as client:
                    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{path_to_process}"
                    headers = {"Authorization": f"Bearer {access_token}"}
                    response = await client.get(url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    item_data = response.json()

                    if "folder" in item_data:
                        # It's a folder - recursively list all files
                        files_to_process = await list_files_recursive(path_to_process)
                    elif "file" in item_data:
                        # It's a single file
                        files_to_process.append((path_to_process, item_data["name"]))
                    else:
                        log_warning(f"SharePoint path {path_to_process} is neither file nor folder")
                        return
            except Exception as e:
                log_error(f"Error checking SharePoint path {path_to_process}: {e}")
                return

        if not files_to_process:
            log_warning(f"No files found at SharePoint path: {path_to_process}")
            return

        # 4. Process each file
        for file_path, file_name in files_to_process:
            # Build a unique virtual path for hashing (ensures different files don't collide)
            virtual_path = f"sharepoint://{sp_config.hostname}/{site_id}/{file_path}"

            # Build metadata with all info needed to re-fetch the file
            sharepoint_metadata = {
                "source_type": "sharepoint",
                "source_config_id": sp_config.id,
                "source_config_name": sp_config.name,
                "sharepoint_hostname": sp_config.hostname,
                "sharepoint_site_id": site_id,
                "sharepoint_path": file_path,
                "sharepoint_filename": file_name,
            }
            # Merge with user-provided metadata (user metadata takes precedence)
            merged_metadata = {**sharepoint_metadata, **(content.metadata or {})}

            # Setup Content object
            # Naming: for folders, use relative path; for single files, use user name or filename
            is_folder_upload = len(files_to_process) > 1
            if is_folder_upload:
                # Compute relative path from the upload root
                relative_path = file_path
                if path_to_process and file_path.startswith(path_to_process + "/"):
                    relative_path = file_path[len(path_to_process) + 1 :]
                # If user provided a name, prefix it; otherwise use full file path
                content_name = f"{content.name}/{relative_path}" if content.name else file_path
            else:
                # Single file: use user's name or the filename
                content_name = content.name or file_name
            content_entry = Content(
                name=content_name,
                description=content.description,
                path=virtual_path,  # Include path for unique hashing
                status=ContentStatus.PROCESSING,
                metadata=merged_metadata,
                file_type="sharepoint",
            )

            # Hash content and add to contents database
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)
            await self._ainsert_contents_db(content_entry)
            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                await self._aupdate_content(content_entry)
                continue

            # Select reader based on file extension
            reader = self._select_reader_by_uri(file_name, content.reader)
            reader = cast(Reader, reader)

            # Download file
            file_content = await self._adownload_sharepoint_file(site_id, file_path, access_token)
            if not file_content:
                content_entry.status = ContentStatus.FAILED
                await self._aupdate_content(content_entry)
                continue

            # Read the content
            read_documents = await reader.async_read(file_content, name=file_name)

            # Prepare and insert to vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_sharepoint(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Synchronous version of _load_from_sharepoint.

        Load content from SharePoint:
        1. Authenticate with Microsoft Graph using client credentials
        2. Get site ID from hostname/site_path
        3. Download file(s) from file_path or folder_path
        4. Process through reader and insert to vector db
        """
        remote_content: SharePointContent = cast(SharePointContent, content.remote_content)
        sp_config = cast(SharePointConfig, config) if isinstance(config, SharePointConfig) else None

        if sp_config is None:
            log_error(f"SharePoint config not found for config_id: {remote_content.config_id}")
            return

        # 1. Get access token
        access_token = self._get_sharepoint_access_token(sp_config)
        if not access_token:
            return

        # 2. Get site ID - use config value if provided, otherwise fetch via API
        site_id: Optional[str] = sp_config.site_id
        if not site_id:
            site_path = remote_content.site_path or sp_config.site_path
            site_id = self._get_sharepoint_site_id(sp_config.hostname, site_path, access_token)
            if not site_id:
                log_error(f"Failed to get SharePoint site ID for {sp_config.hostname}/{site_path}")
                return

        # 3. Identify files to download
        files_to_process: List[tuple] = []  # List of (file_path, file_name)

        # Helper function to recursively list all files in a folder
        def list_files_recursive(folder: str) -> List[tuple]:
            """Recursively list all files in a SharePoint folder."""
            files: List[tuple] = []
            items = self._list_sharepoint_folder_items(site_id, folder, access_token)
            for item in items:
                if "file" in item:  # It's a file
                    item_path = f"{folder}/{item['name']}"
                    files.append((item_path, item["name"]))
                elif "folder" in item:  # It's a folder - recurse
                    subdir_path = f"{folder}/{item['name']}"
                    subdir_files = list_files_recursive(subdir_path)
                    files.extend(subdir_files)
            return files

        # Get the path to process (file_path or folder_path)
        path_to_process = (remote_content.file_path or remote_content.folder_path or "").strip("/")

        if path_to_process:
            # Check if path is a file or folder by getting item metadata
            try:
                with httpx.Client() as client:
                    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{path_to_process}"
                    headers = {"Authorization": f"Bearer {access_token}"}
                    response = client.get(url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    item_data = response.json()

                    if "folder" in item_data:
                        # It's a folder - recursively list all files
                        files_to_process = list_files_recursive(path_to_process)
                    elif "file" in item_data:
                        # It's a single file
                        files_to_process.append((path_to_process, item_data["name"]))
                    else:
                        log_warning(f"SharePoint path {path_to_process} is neither file nor folder")
                        return
            except Exception as e:
                log_error(f"Error checking SharePoint path {path_to_process}: {e}")
                return

        if not files_to_process:
            log_warning(f"No files found at SharePoint path: {path_to_process}")
            return

        # 4. Process each file
        for file_path, file_name in files_to_process:
            # Build a unique virtual path for hashing (ensures different files don't collide)
            virtual_path = f"sharepoint://{sp_config.hostname}/{site_id}/{file_path}"

            # Build metadata with all info needed to re-fetch the file
            sharepoint_metadata = {
                "source_type": "sharepoint",
                "source_config_id": sp_config.id,
                "source_config_name": sp_config.name,
                "sharepoint_hostname": sp_config.hostname,
                "sharepoint_site_id": site_id,
                "sharepoint_path": file_path,
                "sharepoint_filename": file_name,
            }
            # Merge with user-provided metadata (user metadata takes precedence)
            merged_metadata = {**sharepoint_metadata, **(content.metadata or {})}

            # Setup Content object
            # Naming: for folders, use relative path; for single files, use user name or filename
            is_folder_upload = len(files_to_process) > 1
            if is_folder_upload:
                # Compute relative path from the upload root
                relative_path = file_path
                if path_to_process and file_path.startswith(path_to_process + "/"):
                    relative_path = file_path[len(path_to_process) + 1 :]
                # If user provided a name, prefix it; otherwise use full file path
                content_name = f"{content.name}/{relative_path}" if content.name else file_path
            else:
                # Single file: use user's name or the filename
                content_name = content.name or file_name
            content_entry = Content(
                name=content_name,
                description=content.description,
                path=virtual_path,  # Include path for unique hashing
                status=ContentStatus.PROCESSING,
                metadata=merged_metadata,
                file_type="sharepoint",
            )

            # Hash content and add to contents database
            content_entry.content_hash = self._build_content_hash(content_entry)
            content_entry.id = generate_id(content_entry.content_hash)
            self._insert_contents_db(content_entry)
            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                self._update_content(content_entry)
                continue

            # Select reader based on file extension
            reader = self._select_reader_by_uri(file_name, content.reader)
            reader = cast(Reader, reader)

            # Download file
            file_content = self._download_sharepoint_file(site_id, file_path, access_token)
            if not file_content:
                content_entry.status = ContentStatus.FAILED
                self._update_content(content_entry)
                continue

            # Read the content
            read_documents = reader.read(file_content, name=file_name)

            # Prepare and insert to vector database
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            self._handle_vector_db_insert(content_entry, read_documents, upsert)

    # ==========================================
    # GITHUB LOADERS
    # ==========================================

    async def _aload_from_github(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from GitHub.

        Requires the GitHub config to contain repo and optionally token for private repos.
        Uses the GitHub API to fetch file contents.
        """
        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = cast(GitHubConfig, config) if isinstance(config, GitHubConfig) else None

        if gh_config is None:
            log_error(f"GitHub config not found for config_id: {remote_content.config_id}")
            return

        # Build headers for GitHub API
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.token:
            headers["Authorization"] = f"Bearer {gh_config.token}"

        branch = remote_content.branch or gh_config.branch or "main"

        # Get list of files to process
        files_to_process: List[Dict[str, str]] = []

        async with AsyncClient() as client:
            # Helper function to recursively list all files in a folder
            async def list_files_recursive(folder: str) -> List[Dict[str, str]]:
                """Recursively list all files in a GitHub folder."""
                files: List[Dict[str, str]] = []
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{folder}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    items = response.json()

                    # If items is not a list, it's a single file response
                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if item.get("type") == "file":
                            files.append(
                                {
                                    "path": item["path"],
                                    "name": item["name"],
                                }
                            )
                        elif item.get("type") == "dir":
                            # Recursively get files from subdirectory
                            subdir_files = await list_files_recursive(item["path"])
                            files.extend(subdir_files)
                except Exception as e:
                    log_error(f"Error listing GitHub folder {folder}: {e}")

                return files

            # Get the path to process (file_path or folder_path)
            path_to_process = (remote_content.file_path or remote_content.folder_path or "").rstrip("/")

            if path_to_process:
                # Fetch the path to determine if it's a file or directory
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{path_to_process}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    path_data = response.json()

                    if isinstance(path_data, list):
                        # It's a directory - recursively list all files
                        for item in path_data:
                            if item.get("type") == "file":
                                files_to_process.append({"path": item["path"], "name": item["name"]})
                            elif item.get("type") == "dir":
                                subdir_files = await list_files_recursive(item["path"])
                                files_to_process.extend(subdir_files)
                    else:
                        # It's a single file
                        files_to_process.append(
                            {
                                "path": path_data["path"],
                                "name": path_data["name"],
                            }
                        )
                except Exception as e:
                    log_error(f"Error fetching GitHub path {path_to_process}: {e}")
                    return

            if not files_to_process:
                log_warning(f"No files found at GitHub path: {path_to_process}")
                return

            # Process each file
            for file_info in files_to_process:
                file_path = file_info["path"]
                file_name = file_info["name"]

                # Build a unique virtual path for hashing (ensures different files don't collide)
                virtual_path = f"github://{gh_config.repo}/{branch}/{file_path}"

                # Build metadata with all info needed to re-fetch the file
                github_metadata = {
                    "source_type": "github",
                    "source_config_id": gh_config.id,
                    "source_config_name": gh_config.name,
                    "github_repo": gh_config.repo,
                    "github_branch": branch,
                    "github_path": file_path,
                    "github_filename": file_name,
                }
                # Merge with user-provided metadata (user metadata takes precedence)
                merged_metadata = {**github_metadata, **(content.metadata or {})}

                # Setup Content object
                # Naming: for folders, use relative path; for single files, use user name or filename
                is_folder_upload = len(files_to_process) > 1
                if is_folder_upload:
                    # Compute relative path from the upload root
                    relative_path = file_path
                    if path_to_process and file_path.startswith(path_to_process + "/"):
                        relative_path = file_path[len(path_to_process) + 1 :]
                    # If user provided a name, prefix it; otherwise use full file path
                    content_name = f"{content.name}/{relative_path}" if content.name else file_path
                else:
                    # Single file: use user's name or the filename
                    content_name = content.name or file_name
                content_entry = Content(
                    name=content_name,
                    description=content.description,
                    path=virtual_path,  # Include path for unique hashing
                    status=ContentStatus.PROCESSING,
                    metadata=merged_metadata,
                    file_type="github",
                )

                # Hash content and add to contents database
                content_entry.content_hash = self._build_content_hash(content_entry)
                content_entry.id = generate_id(content_entry.content_hash)
                await self._ainsert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    await self._aupdate_content(content_entry)
                    continue

                # Fetch file content using GitHub API (works for private repos)
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{file_path}"
                if branch:
                    api_url += f"?ref={branch}"
                try:
                    response = await client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    file_data = response.json()

                    # GitHub API returns content as base64
                    if file_data.get("encoding") == "base64":
                        import base64

                        file_content = base64.b64decode(file_data["content"])
                    else:
                        # For large files, GitHub returns a download_url
                        download_url = file_data.get("download_url")
                        if download_url:
                            dl_response = await client.get(download_url, headers=headers, timeout=30.0)
                            dl_response.raise_for_status()
                            file_content = dl_response.content
                        else:
                            raise ValueError("No content or download_url in response")
                except Exception as e:
                    log_error(f"Error fetching GitHub file {file_path}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    await self._aupdate_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    await self._aupdate_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                readable_content = BytesIO(file_content)
                read_documents = await reader.async_read(readable_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_github(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Synchronous version of _load_from_github."""
        import httpx

        remote_content: GitHubContent = cast(GitHubContent, content.remote_content)
        gh_config = cast(GitHubConfig, config) if isinstance(config, GitHubConfig) else None

        if gh_config is None:
            log_error(f"GitHub config not found for config_id: {remote_content.config_id}")
            return

        # Build headers for GitHub API
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Agno-Knowledge",
        }
        if gh_config.token:
            headers["Authorization"] = f"Bearer {gh_config.token}"

        branch = remote_content.branch or gh_config.branch or "main"

        # Get list of files to process
        files_to_process: List[Dict[str, str]] = []

        with httpx.Client() as client:
            # Helper function to recursively list all files in a folder
            def list_files_recursive(folder: str) -> List[Dict[str, str]]:
                """Recursively list all files in a GitHub folder."""
                files: List[Dict[str, str]] = []
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{folder}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    items = response.json()

                    # If items is not a list, it's a single file response
                    if not isinstance(items, list):
                        items = [items]

                    for item in items:
                        if item.get("type") == "file":
                            files.append(
                                {
                                    "path": item["path"],
                                    "name": item["name"],
                                }
                            )
                        elif item.get("type") == "dir":
                            # Recursively get files from subdirectory
                            subdir_files = list_files_recursive(item["path"])
                            files.extend(subdir_files)
                except Exception as e:
                    log_error(f"Error listing GitHub folder {folder}: {e}")

                return files

            # Get the path to process (file_path or folder_path)
            path_to_process = (remote_content.file_path or remote_content.folder_path or "").rstrip("/")

            if path_to_process:
                # Fetch the path to determine if it's a file or directory
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{path_to_process}"
                if branch:
                    api_url += f"?ref={branch}"

                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    path_data = response.json()

                    if isinstance(path_data, list):
                        # It's a directory - recursively list all files
                        for item in path_data:
                            if item.get("type") == "file":
                                files_to_process.append({"path": item["path"], "name": item["name"]})
                            elif item.get("type") == "dir":
                                subdir_files = list_files_recursive(item["path"])
                                files_to_process.extend(subdir_files)
                    else:
                        # It's a single file
                        files_to_process.append(
                            {
                                "path": path_data["path"],
                                "name": path_data["name"],
                            }
                        )
                except Exception as e:
                    log_error(f"Error fetching GitHub path {path_to_process}: {e}")
                    return

            if not files_to_process:
                log_warning(f"No files found at GitHub path: {path_to_process}")
                return

            # Process each file
            for file_info in files_to_process:
                file_path = file_info["path"]
                file_name = file_info["name"]

                # Build a unique virtual path for hashing (ensures different files don't collide)
                virtual_path = f"github://{gh_config.repo}/{branch}/{file_path}"

                # Build metadata with all info needed to re-fetch the file
                github_metadata = {
                    "source_type": "github",
                    "source_config_id": gh_config.id,
                    "source_config_name": gh_config.name,
                    "github_repo": gh_config.repo,
                    "github_branch": branch,
                    "github_path": file_path,
                    "github_filename": file_name,
                }
                # Merge with user-provided metadata (user metadata takes precedence)
                merged_metadata = {**github_metadata, **(content.metadata or {})}

                # Setup Content object
                # Naming: for folders, use relative path; for single files, use user name or filename
                is_folder_upload = len(files_to_process) > 1
                if is_folder_upload:
                    # Compute relative path from the upload root
                    relative_path = file_path
                    if path_to_process and file_path.startswith(path_to_process + "/"):
                        relative_path = file_path[len(path_to_process) + 1 :]
                    # If user provided a name, prefix it; otherwise use full file path
                    content_name = f"{content.name}/{relative_path}" if content.name else file_path
                else:
                    # Single file: use user's name or the filename
                    content_name = content.name or file_name
                content_entry = Content(
                    name=content_name,
                    description=content.description,
                    path=virtual_path,  # Include path for unique hashing
                    status=ContentStatus.PROCESSING,
                    metadata=merged_metadata,
                    file_type="github",
                )

                # Hash content and add to contents database
                content_entry.content_hash = self._build_content_hash(content_entry)
                content_entry.id = generate_id(content_entry.content_hash)
                self._insert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    self._update_content(content_entry)
                    continue

                # Fetch file content using GitHub API (works for private repos)
                api_url = f"https://api.github.com/repos/{gh_config.repo}/contents/{file_path}"
                if branch:
                    api_url += f"?ref={branch}"
                try:
                    response = client.get(api_url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    file_data = response.json()

                    # GitHub API returns content as base64
                    if file_data.get("encoding") == "base64":
                        import base64

                        file_content = base64.b64decode(file_data["content"])
                    else:
                        # For large files, GitHub returns a download_url
                        download_url = file_data.get("download_url")
                        if download_url:
                            dl_response = client.get(download_url, headers=headers, timeout=30.0)
                            dl_response.raise_for_status()
                            file_content = dl_response.content
                        else:
                            raise ValueError("No content or download_url in response")
                except Exception as e:
                    log_error(f"Error fetching GitHub file {file_path}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    self._update_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    self._update_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                readable_content = BytesIO(file_content)
                read_documents = reader.read(readable_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                self._handle_vector_db_insert(content_entry, read_documents, upsert)

    # ==========================================
    # AZURE BLOB HELPERS
    # ==========================================

    def _get_azure_blob_client(self, azure_config: AzureBlobConfig):
        """Get a sync Azure Blob Service Client using client credentials flow.

        Requires the `azure-identity` and `azure-storage-blob` packages.
        """
        try:
            from azure.identity import ClientSecretCredential  # type: ignore
            from azure.storage.blob import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        credential = ClientSecretCredential(
            tenant_id=azure_config.tenant_id,
            client_id=azure_config.client_id,
            client_secret=azure_config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{azure_config.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        return blob_service

    def _get_azure_blob_client_async(self, azure_config: AzureBlobConfig):
        """Get an async Azure Blob Service Client using client credentials flow.

        Requires the `azure-identity` and `azure-storage-blob` packages.
        Uses the async versions from azure.storage.blob.aio and azure.identity.aio.
        """
        try:
            from azure.identity.aio import ClientSecretCredential  # type: ignore
            from azure.storage.blob.aio import BlobServiceClient  # type: ignore
        except ImportError:
            raise ImportError(
                "The `azure-identity` and `azure-storage-blob` packages are not installed. "
                "Please install them via `pip install azure-identity azure-storage-blob`."
            )

        credential = ClientSecretCredential(
            tenant_id=azure_config.tenant_id,
            client_id=azure_config.client_id,
            client_secret=azure_config.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{azure_config.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        return blob_service

    # ==========================================
    # AZURE BLOB LOADERS
    # ==========================================

    async def _aload_from_azure_blob(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Load content from Azure Blob Storage (async version).

        Requires the AzureBlobConfig to contain tenant_id, client_id, client_secret,
        storage_account, and container.

        Uses the async Azure SDK to avoid blocking the event loop.

        1. Authenticate with Azure AD using client credentials
        2. List blobs in container (by prefix or single blob)
        3. Download and process each blob
        4. Insert to vector database
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = cast(AzureBlobConfig, config) if isinstance(config, AzureBlobConfig) else None

        if azure_config is None:
            log_error(f"Azure Blob config not found for config_id: {remote_content.config_id}")
            return

        # Get async blob service client
        try:
            blob_service = self._get_azure_blob_client_async(azure_config)
        except ImportError as e:
            log_error(str(e))
            return
        except Exception as e:
            log_error(f"Error creating Azure Blob client: {e}")
            return

        # Use async context manager for proper resource cleanup
        async with blob_service:
            container_client = blob_service.get_container_client(azure_config.container)

            # Helper to list blobs with a given prefix (async)
            async def list_blobs_with_prefix(prefix: str) -> List[Dict[str, Any]]:
                """List all blobs under a given prefix (folder)."""
                results: List[Dict[str, Any]] = []
                normalized_prefix = prefix.rstrip("/") + "/" if not prefix.endswith("/") else prefix
                async for blob in container_client.list_blobs(name_starts_with=normalized_prefix):
                    # Skip "directory" markers (blobs ending with /)
                    if not blob.name.endswith("/"):
                        results.append(
                            {
                                "name": blob.name,
                                "size": blob.size,
                                "content_type": blob.content_settings.content_type if blob.content_settings else None,
                            }
                        )
                return results

            # Identify blobs to process
            blobs_to_process: List[Dict[str, Any]] = []

            try:
                if remote_content.blob_name:
                    # Try to get as a single blob first
                    blob_client = container_client.get_blob_client(remote_content.blob_name)
                    try:
                        props = await blob_client.get_blob_properties()
                        blobs_to_process.append(
                            {
                                "name": remote_content.blob_name,
                                "size": props.size,
                                "content_type": props.content_settings.content_type if props.content_settings else None,
                            }
                        )
                    except Exception:
                        # Blob doesn't exist - check if it's actually a folder (prefix)
                        log_debug(f"Blob {remote_content.blob_name} not found, checking if it's a folder...")
                        blobs_to_process = await list_blobs_with_prefix(remote_content.blob_name)
                        if not blobs_to_process:
                            log_error(
                                f"No blob or folder found at path: {remote_content.blob_name}. "
                                "If this is a folder, ensure files exist inside it."
                            )
                            return
                elif remote_content.prefix:
                    # List blobs with prefix
                    blobs_to_process = await list_blobs_with_prefix(remote_content.prefix)
            except Exception as e:
                log_error(f"Error listing Azure blobs: {e}")
                return

            if not blobs_to_process:
                log_warning(f"No blobs found in Azure container: {azure_config.container}")
                return

            # For single file uploads, use the original content object to preserve the ID
            # returned by the API. For folder uploads, create new content entries for each file.
            is_folder_upload = len(blobs_to_process) > 1

            # Process each blob
            for blob_info in blobs_to_process:
                blob_name = blob_info["name"]
                file_name = blob_name.split("/")[-1]

                # Build a unique virtual path for hashing
                virtual_path = f"azure://{azure_config.storage_account}/{azure_config.container}/{blob_name}"

                # Build metadata
                azure_metadata = {
                    "source_type": "azure_blob",
                    "source_config_id": azure_config.id,
                    "source_config_name": azure_config.name,
                    "azure_storage_account": azure_config.storage_account,
                    "azure_container": azure_config.container,
                    "azure_blob_name": blob_name,
                    "azure_filename": file_name,
                }
                merged_metadata = {**azure_metadata, **(content.metadata or {})}

                # Setup Content object
                if is_folder_upload:
                    # For folder uploads, create new content entries for each file
                    relative_path = blob_name
                    if remote_content.prefix and blob_name.startswith(remote_content.prefix):
                        relative_path = blob_name[len(remote_content.prefix) :].lstrip("/")
                    content_name = f"{content.name}/{relative_path}" if content.name else blob_name

                    content_entry = Content(
                        name=content_name,
                        description=content.description,
                        path=virtual_path,
                        status=ContentStatus.PROCESSING,
                        metadata=merged_metadata,
                        file_type="azure_blob",
                    )
                    content_entry.content_hash = self._build_content_hash(content_entry)
                    content_entry.id = generate_id(content_entry.content_hash)
                else:
                    # For single file uploads, use the original content object to preserve ID
                    content_entry = content
                    content_entry.path = virtual_path
                    content_entry.status = ContentStatus.PROCESSING
                    content_entry.metadata = merged_metadata
                    content_entry.file_type = "azure_blob"
                    # Use existing id and content_hash from the original content if available
                    if not content_entry.content_hash:
                        content_entry.content_hash = self._build_content_hash(content_entry)
                    if not content_entry.id:
                        content_entry.id = generate_id(content_entry.content_hash)

                await self._ainsert_contents_db(content_entry)

                if self._should_skip(content_entry.content_hash, skip_if_exists):
                    content_entry.status = ContentStatus.COMPLETED
                    await self._aupdate_content(content_entry)
                    continue

                # Download blob (async)
                try:
                    blob_client = container_client.get_blob_client(blob_name)
                    download_stream = await blob_client.download_blob()
                    blob_data = await download_stream.readall()
                    file_content = BytesIO(blob_data)
                except Exception as e:
                    log_error(f"Error downloading Azure blob {blob_name}: {e}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = str(e)
                    await self._aupdate_content(content_entry)
                    continue

                # Select reader and read content
                reader = self._select_reader_by_uri(file_name, content.reader)
                if reader is None:
                    log_warning(f"No reader found for file: {file_name}")
                    content_entry.status = ContentStatus.FAILED
                    content_entry.status_message = "No suitable reader found"
                    await self._aupdate_content(content_entry)
                    continue

                reader = cast(Reader, reader)
                read_documents = await reader.async_read(file_content, name=file_name)

                # Prepare and insert into vector database
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash or "")
                self._prepare_documents_for_insert(read_documents, content_entry.id)
                await self._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_azure_blob(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[RemoteContentConfig] = None,
    ):
        """Synchronous version of _load_from_azure_blob.

        Load content from Azure Blob Storage:
        1. Authenticate with Azure AD using client credentials
        2. List blobs in container (by prefix or single blob)
        3. Download and process each blob
        4. Insert to vector database
        """
        remote_content: AzureBlobContent = cast(AzureBlobContent, content.remote_content)
        azure_config = cast(AzureBlobConfig, config) if isinstance(config, AzureBlobConfig) else None

        if azure_config is None:
            log_error(f"Azure Blob config not found for config_id: {remote_content.config_id}")
            return

        # Get blob service client
        try:
            blob_service = self._get_azure_blob_client(azure_config)
        except ImportError as e:
            log_error(str(e))
            return
        except Exception as e:
            log_error(f"Error creating Azure Blob client: {e}")
            return

        container_client = blob_service.get_container_client(azure_config.container)

        # Helper to list blobs with a given prefix
        def list_blobs_with_prefix(prefix: str) -> List[Dict[str, Any]]:
            """List all blobs under a given prefix (folder)."""
            results: List[Dict[str, Any]] = []
            normalized_prefix = prefix.rstrip("/") + "/" if not prefix.endswith("/") else prefix
            blobs = container_client.list_blobs(name_starts_with=normalized_prefix)
            for blob in blobs:
                # Skip "directory" markers (blobs ending with /)
                if not blob.name.endswith("/"):
                    results.append(
                        {
                            "name": blob.name,
                            "size": blob.size,
                            "content_type": blob.content_settings.content_type if blob.content_settings else None,
                        }
                    )
            return results

        # Identify blobs to process
        blobs_to_process: List[Dict[str, Any]] = []

        try:
            if remote_content.blob_name:
                # Try to get as a single blob first
                blob_client = container_client.get_blob_client(remote_content.blob_name)
                try:
                    props = blob_client.get_blob_properties()
                    blobs_to_process.append(
                        {
                            "name": remote_content.blob_name,
                            "size": props.size,
                            "content_type": props.content_settings.content_type if props.content_settings else None,
                        }
                    )
                except Exception:
                    # Blob doesn't exist - check if it's actually a folder (prefix)
                    log_debug(f"Blob {remote_content.blob_name} not found, checking if it's a folder...")
                    blobs_to_process = list_blobs_with_prefix(remote_content.blob_name)
                    if not blobs_to_process:
                        log_error(
                            f"No blob or folder found at path: {remote_content.blob_name}. "
                            "If this is a folder, ensure files exist inside it."
                        )
                        return
            elif remote_content.prefix:
                # List blobs with prefix
                blobs_to_process = list_blobs_with_prefix(remote_content.prefix)
        except Exception as e:
            log_error(f"Error listing Azure blobs: {e}")
            return

        if not blobs_to_process:
            log_warning(f"No blobs found in Azure container: {azure_config.container}")
            return

        # For single file uploads, use the original content object to preserve the ID
        # returned by the API. For folder uploads, create new content entries for each file.
        is_folder_upload = len(blobs_to_process) > 1

        # Process each blob
        for blob_info in blobs_to_process:
            blob_name = blob_info["name"]
            file_name = blob_name.split("/")[-1]

            # Build a unique virtual path for hashing
            virtual_path = f"azure://{azure_config.storage_account}/{azure_config.container}/{blob_name}"

            # Build metadata
            azure_metadata = {
                "source_type": "azure_blob",
                "source_config_id": azure_config.id,
                "source_config_name": azure_config.name,
                "azure_storage_account": azure_config.storage_account,
                "azure_container": azure_config.container,
                "azure_blob_name": blob_name,
                "azure_filename": file_name,
            }
            merged_metadata = {**azure_metadata, **(content.metadata or {})}

            # Setup Content object
            if is_folder_upload:
                # For folder uploads, create new content entries for each file
                relative_path = blob_name
                if remote_content.prefix and blob_name.startswith(remote_content.prefix):
                    relative_path = blob_name[len(remote_content.prefix) :].lstrip("/")
                content_name = f"{content.name}/{relative_path}" if content.name else blob_name

                content_entry = Content(
                    name=content_name,
                    description=content.description,
                    path=virtual_path,
                    status=ContentStatus.PROCESSING,
                    metadata=merged_metadata,
                    file_type="azure_blob",
                )
                content_entry.content_hash = self._build_content_hash(content_entry)
                content_entry.id = generate_id(content_entry.content_hash)
            else:
                # For single file uploads, use the original content object to preserve ID
                content_entry = content
                content_entry.path = virtual_path
                content_entry.status = ContentStatus.PROCESSING
                content_entry.metadata = merged_metadata
                content_entry.file_type = "azure_blob"
                # Use existing id and content_hash from the original content if available
                if not content_entry.content_hash:
                    content_entry.content_hash = self._build_content_hash(content_entry)
                if not content_entry.id:
                    content_entry.id = generate_id(content_entry.content_hash)

            self._insert_contents_db(content_entry)

            if self._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                self._update_content(content_entry)
                continue

            # Download blob
            try:
                blob_client = container_client.get_blob_client(blob_name)
                download_stream = blob_client.download_blob()
                file_content = BytesIO(download_stream.readall())
            except Exception as e:
                log_error(f"Error downloading Azure blob {blob_name}: {e}")
                content_entry.status = ContentStatus.FAILED
                content_entry.status_message = str(e)
                self._update_content(content_entry)
                continue

            # Select reader and read content
            reader = self._select_reader_by_uri(file_name, content.reader)
            if reader is None:
                log_warning(f"No reader found for file: {file_name}")
                content_entry.status = ContentStatus.FAILED
                content_entry.status_message = "No suitable reader found"
                self._update_content(content_entry)
                continue

            reader = cast(Reader, reader)
            read_documents = reader.read(file_content, name=file_name)

            # Prepare and insert into vector database
            if not content_entry.id:
                content_entry.id = generate_id(content_entry.content_hash or "")
            self._prepare_documents_for_insert(read_documents, content_entry.id)
            self._handle_vector_db_insert(content_entry, read_documents, upsert)

    # ==========================================
    # REMOTE CONFIG HELPERS
    # ==========================================

    def _get_remote_configs(self) -> List[RemoteContentConfig]:
        """Return configured remote content sources."""
        return self.content_sources or []

    def _get_remote_config_by_id(self, config_id: str) -> Optional[RemoteContentConfig]:
        """Get a remote content config by its ID."""
        if not self.content_sources:
            return None
        return next((c for c in self.content_sources if c.id == config_id), None)

    # ==========================================
    # ABSTRACT METHODS (implemented by Knowledge)
    # ==========================================
    # These methods are provided by the Knowledge subclass

    def _should_skip(self, content_hash: str, skip_if_exists: bool) -> bool:
        """Check if content should be skipped based on hash."""
        raise NotImplementedError("Subclass must implement _should_skip")

    def _select_reader_by_uri(self, uri: str, reader: Optional[Reader]) -> Optional[Reader]:
        """Select appropriate reader for a URI."""
        raise NotImplementedError("Subclass must implement _select_reader_by_uri")

    def _prepare_documents_for_insert(self, documents: List[Any], content_id: str) -> None:
        """Prepare documents for vector DB insertion."""
        raise NotImplementedError("Subclass must implement _prepare_documents_for_insert")

    def _build_content_hash(self, content: Content) -> str:
        """Build hash for content."""
        raise NotImplementedError("Subclass must implement _build_content_hash")

    async def _ahandle_vector_db_insert(self, content: Content, read_documents: List[Any], upsert: bool) -> None:
        """Handle async vector DB insertion."""
        raise NotImplementedError("Subclass must implement _ahandle_vector_db_insert")

    def _handle_vector_db_insert(self, content: Content, read_documents: List[Any], upsert: bool) -> None:
        """Handle sync vector DB insertion."""
        raise NotImplementedError("Subclass must implement _handle_vector_db_insert")

    async def _ainsert_contents_db(self, content: Content) -> None:
        """Insert content into contents database (async)."""
        raise NotImplementedError("Subclass must implement _ainsert_contents_db")

    def _insert_contents_db(self, content: Content) -> None:
        """Insert content into contents database (sync)."""
        raise NotImplementedError("Subclass must implement _insert_contents_db")

    async def _aupdate_content(self, content: Content) -> None:
        """Update content in contents database (async)."""
        raise NotImplementedError("Subclass must implement _aupdate_content")

    def _update_content(self, content: Content) -> None:
        """Update content in contents database (sync)."""
        raise NotImplementedError("Subclass must implement _update_content")
