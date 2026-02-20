"""SharePoint content loader for Knowledge.

Provides methods for loading content from Microsoft SharePoint.
"""

from io import BytesIO
from typing import Dict, List, Optional, cast

import httpx
from httpx import AsyncClient

from agno.knowledge.content import Content, ContentStatus
from agno.knowledge.loaders.base import BaseLoader
from agno.knowledge.reader import Reader
from agno.knowledge.remote_content.base import BaseStorageConfig
from agno.knowledge.remote_content.remote_content import SharePointContent
from agno.knowledge.remote_content.sharepoint import SharePointConfig
from agno.utils.log import log_error, log_info, log_warning


class SharePointLoader(BaseLoader):
    """Loader for SharePoint content."""

    # ==========================================
    # SHAREPOINT HELPERS (shared between sync/async)
    # ==========================================

    def _validate_sharepoint_config(
        self,
        content: Content,
        config: Optional[BaseStorageConfig],
    ) -> Optional[SharePointConfig]:
        """Validate and extract SharePoint config.

        Returns:
            SharePointConfig if valid, None otherwise
        """
        remote_content: SharePointContent = cast(SharePointContent, content.remote_content)
        sp_config = cast(SharePointConfig, config) if isinstance(config, SharePointConfig) else None

        if sp_config is None:
            log_error(f"SharePoint config not found for config_id: {remote_content.config_id}")
            return None

        return sp_config

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

        scopes = ["https://graph.microsoft.com/.default"]
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:
            return result["access_token"]
        else:
            log_error(f"Failed to acquire SharePoint token: {result.get('error_description', result.get('error'))}")
            return None

    def _get_sharepoint_site_id(self, hostname: str, site_path: Optional[str], access_token: str) -> Optional[str]:
        """Get the SharePoint site ID using Microsoft Graph API (sync)."""
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

    async def _aget_sharepoint_site_id(
        self, hostname: str, site_path: Optional[str], access_token: str
    ) -> Optional[str]:
        """Get the SharePoint site ID using Microsoft Graph API (async)."""
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

    def _list_sharepoint_folder_items(self, site_id: str, folder_path: str, access_token: str) -> List[dict]:
        """List all items in a SharePoint folder (sync)."""
        folder_path = folder_path.lstrip("/")
        url: Optional[str] = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{folder_path}:/children"
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

    async def _alist_sharepoint_folder_items(self, site_id: str, folder_path: str, access_token: str) -> List[dict]:
        """List all items in a SharePoint folder (async)."""
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

    def _download_sharepoint_file(self, site_id: str, file_path: str, access_token: str) -> Optional[BytesIO]:
        """Download a file from SharePoint (sync)."""
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

    async def _adownload_sharepoint_file(self, site_id: str, file_path: str, access_token: str) -> Optional[BytesIO]:
        """Download a file from SharePoint (async)."""
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

    def _build_sharepoint_metadata(
        self,
        sp_config: SharePointConfig,
        site_id: str,
        file_path: str,
        file_name: str,
    ) -> Dict[str, str]:
        """Build SharePoint-specific metadata dictionary."""
        return {
            "source_type": "sharepoint",
            "source_config_id": sp_config.id,
            "source_config_name": sp_config.name,
            "sharepoint_hostname": sp_config.hostname,
            "sharepoint_site_id": site_id,
            "sharepoint_path": file_path,
            "sharepoint_filename": file_name,
        }

    def _build_sharepoint_virtual_path(self, hostname: str, site_id: str, file_path: str) -> str:
        """Build virtual path for SharePoint content."""
        return f"sharepoint://{hostname}/{site_id}/{file_path}"

    def _get_sharepoint_path_to_process(self, remote_content: SharePointContent) -> str:
        """Get the path to process from remote content."""
        return (remote_content.file_path or remote_content.folder_path or "").strip("/")

    # ==========================================
    # SHAREPOINT LOADERS
    # ==========================================

    async def _aload_from_sharepoint(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[BaseStorageConfig] = None,
    ):
        """Load content from SharePoint (async).

        Requires the SharePoint config to contain tenant_id, client_id, client_secret, and hostname.
        """
        remote_content: SharePointContent = cast(SharePointContent, content.remote_content)
        sp_config = self._validate_sharepoint_config(content, config)
        if sp_config is None:
            return

        # Get access token
        access_token = self._get_sharepoint_access_token(sp_config)
        if not access_token:
            return

        # Get site ID
        site_id: Optional[str] = sp_config.site_id
        if not site_id:
            site_path = remote_content.site_path or sp_config.site_path
            site_id = await self._aget_sharepoint_site_id(sp_config.hostname, site_path, access_token)
            if not site_id:
                log_error(f"Failed to get SharePoint site ID for {sp_config.hostname}/{site_path}")
                return

        # Identify files to download
        files_to_process: List[tuple] = []
        path_to_process = self._get_sharepoint_path_to_process(remote_content)

        # Helper function to recursively list all files in a folder
        async def list_files_recursive(folder: str) -> List[tuple]:
            """Recursively list all files in a SharePoint folder."""
            files: List[tuple] = []
            items = await self._alist_sharepoint_folder_items(site_id, folder, access_token)  # type: ignore
            for item in items:
                if "file" in item:
                    item_path = f"{folder}/{item['name']}"
                    files.append((item_path, item["name"]))
                elif "folder" in item:
                    subdir_path = f"{folder}/{item['name']}"
                    subdir_files = await list_files_recursive(subdir_path)
                    files.extend(subdir_files)
            return files

        if path_to_process:
            try:
                async with AsyncClient() as client:
                    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{path_to_process}"
                    headers = {"Authorization": f"Bearer {access_token}"}
                    response = await client.get(url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    item_data = response.json()

                    if "folder" in item_data:
                        files_to_process = await list_files_recursive(path_to_process)
                    elif "file" in item_data:
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

        log_info(f"Processing {len(files_to_process)} file(s) from SharePoint")
        is_folder_upload = len(files_to_process) > 1

        for file_path, file_name in files_to_process:
            # Build metadata and virtual path using helpers
            virtual_path = self._build_sharepoint_virtual_path(sp_config.hostname, site_id, file_path)
            sharepoint_metadata = self._build_sharepoint_metadata(sp_config, site_id, file_path, file_name)
            merged_metadata = self._merge_metadata(sharepoint_metadata, content.metadata)

            # Compute content name using base helper
            content_name = self._compute_content_name(
                file_path, file_name, content.name, path_to_process, is_folder_upload
            )

            # Create content entry using base helper
            content_entry = self._create_content_entry(
                content, content_name, virtual_path, merged_metadata, "sharepoint", is_folder_upload
            )

            await self.knowledge._ainsert_contents_db(content_entry)

            if self.knowledge._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                await self.knowledge._aupdate_content(content_entry)
                continue

            # Select reader and download file
            reader = self.knowledge._select_reader_by_uri(file_name, content.reader)
            reader = cast(Reader, reader)

            file_content = await self._adownload_sharepoint_file(site_id, file_path, access_token)
            if not file_content:
                content_entry.status = ContentStatus.FAILED
                await self.knowledge._aupdate_content(content_entry)
                continue

            # Read the content
            read_documents = await reader.async_read(file_content, name=file_name)

            # Prepare and insert to vector database
            self.knowledge._prepare_documents_for_insert(read_documents, content_entry.id)
            await self.knowledge._ahandle_vector_db_insert(content_entry, read_documents, upsert)

    def _load_from_sharepoint(
        self,
        content: Content,
        upsert: bool,
        skip_if_exists: bool,
        config: Optional[BaseStorageConfig] = None,
    ):
        """Load content from SharePoint (sync).

        Requires the SharePoint config to contain tenant_id, client_id, client_secret, and hostname.
        """
        remote_content: SharePointContent = cast(SharePointContent, content.remote_content)
        sp_config = self._validate_sharepoint_config(content, config)
        if sp_config is None:
            return

        # Get access token
        access_token = self._get_sharepoint_access_token(sp_config)
        if not access_token:
            return

        # Get site ID
        site_id: Optional[str] = sp_config.site_id
        if not site_id:
            site_path = remote_content.site_path or sp_config.site_path
            site_id = self._get_sharepoint_site_id(sp_config.hostname, site_path, access_token)
            if not site_id:
                log_error(f"Failed to get SharePoint site ID for {sp_config.hostname}/{site_path}")
                return

        # Identify files to download
        files_to_process: List[tuple] = []
        path_to_process = self._get_sharepoint_path_to_process(remote_content)

        # Helper function to recursively list all files in a folder
        def list_files_recursive(folder: str) -> List[tuple]:
            """Recursively list all files in a SharePoint folder."""
            files: List[tuple] = []
            items = self._list_sharepoint_folder_items(site_id, folder, access_token)  # type: ignore
            for item in items:
                if "file" in item:
                    item_path = f"{folder}/{item['name']}"
                    files.append((item_path, item["name"]))
                elif "folder" in item:
                    subdir_path = f"{folder}/{item['name']}"
                    subdir_files = list_files_recursive(subdir_path)
                    files.extend(subdir_files)
            return files

        if path_to_process:
            try:
                with httpx.Client() as client:
                    url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{path_to_process}"
                    headers = {"Authorization": f"Bearer {access_token}"}
                    response = client.get(url, headers=headers, timeout=30.0)
                    response.raise_for_status()
                    item_data = response.json()

                    if "folder" in item_data:
                        files_to_process = list_files_recursive(path_to_process)
                    elif "file" in item_data:
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

        log_info(f"Processing {len(files_to_process)} file(s) from SharePoint")
        is_folder_upload = len(files_to_process) > 1

        for file_path, file_name in files_to_process:
            # Build metadata and virtual path using helpers
            virtual_path = self._build_sharepoint_virtual_path(sp_config.hostname, site_id, file_path)
            sharepoint_metadata = self._build_sharepoint_metadata(sp_config, site_id, file_path, file_name)
            merged_metadata = self._merge_metadata(sharepoint_metadata, content.metadata)

            # Compute content name using base helper
            content_name = self._compute_content_name(
                file_path, file_name, content.name, path_to_process, is_folder_upload
            )

            # Create content entry using base helper
            content_entry = self._create_content_entry(
                content, content_name, virtual_path, merged_metadata, "sharepoint", is_folder_upload
            )

            self.knowledge._insert_contents_db(content_entry)

            if self.knowledge._should_skip(content_entry.content_hash, skip_if_exists):
                content_entry.status = ContentStatus.COMPLETED
                self.knowledge._update_content(content_entry)
                continue

            # Select reader and download file
            reader = self.knowledge._select_reader_by_uri(file_name, content.reader)
            reader = cast(Reader, reader)

            file_content = self._download_sharepoint_file(site_id, file_path, access_token)
            if not file_content:
                content_entry.status = ContentStatus.FAILED
                self.knowledge._update_content(content_entry)
                continue

            # Read the content
            read_documents = reader.read(file_content, name=file_name)

            # Prepare and insert to vector database
            self.knowledge._prepare_documents_for_insert(read_documents, content_entry.id)
            self.knowledge._handle_vector_db_insert(content_entry, read_documents, upsert)
