from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import (
        AzureBlobContent,
        GCSContent,
        GitHubContent,
        S3Content,
        SharePointContent,
    )


class ListFilesResult:
    """Result of listing files from a remote source."""

    def __init__(
        self,
        files: list,
        folders: list,
        page: int = 1,
        limit: int = 100,
        total_count: int = 0,
        total_pages: int = 0,
    ):
        self.files = files
        self.folders = folders
        self.page = page
        self.limit = limit
        self.total_count = total_count
        self.total_pages = total_pages


# Alias for backward compatibility
S3ListFilesResult = ListFilesResult


class RemoteContentConfig(BaseModel):
    """Base configuration for remote content sources."""

    id: str
    name: str
    metadata: Optional[dict] = None

    model_config = ConfigDict(extra="allow")


class S3Config(RemoteContentConfig):
    """Configuration for AWS S3 content source."""

    bucket_name: str
    region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    prefix: Optional[str] = None

    def list_files(
        self,
        prefix: Optional[str] = None,
        delimiter: str = "/",
        limit: int = 100,
        page: int = 1,
    ) -> S3ListFilesResult:
        """List files and folders in this S3 source with pagination.

        Args:
            prefix: Path prefix to filter files (e.g., "reports/2024/")
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request (1-1000)
            page: Page number (1-indexed)

        Returns:
            S3ListFilesResult with files, folders, and pagination info

        Note:
            S3 uses cursor-based pagination internally. For page > 1, this method
            iterates through previous pages which may be slow for deep pagination.
        """
        try:
            import boto3
        except ImportError:
            raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")

        # Build session kwargs
        session_kwargs = {}
        if self.region:
            session_kwargs["region_name"] = self.region

        # Build client kwargs for credentials
        client_kwargs = {}
        if self.aws_access_key_id and self.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = self.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key

        session = boto3.Session(**session_kwargs)
        s3_client = session.client("s3", **client_kwargs)

        # Use provided prefix or fall back to config prefix
        effective_prefix = prefix if prefix is not None else (self.prefix or "")

        # Count total objects for pagination info
        # Use a paginator to count all matching objects efficiently
        total_count = 0
        count_paginator = s3_client.get_paginator("list_objects_v2")
        count_kwargs = {"Bucket": self.bucket_name}
        if effective_prefix:
            count_kwargs["Prefix"] = effective_prefix
        if delimiter:
            count_kwargs["Delimiter"] = delimiter

        for count_page in count_paginator.paginate(**count_kwargs):
            # Count files (Contents) excluding the prefix marker itself
            for obj in count_page.get("Contents", []):
                key = obj.get("Key", "")
                if key != effective_prefix and (key.rsplit("/", 1)[-1] if "/" in key else key):
                    total_count += 1

        total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

        # For page > 1, we need to skip previous pages
        # S3 uses cursor-based pagination, so we iterate to find the right cursor
        continuation_token = None
        if page > 1:
            for _ in range(page - 1):
                skip_kwargs = {
                    "Bucket": self.bucket_name,
                    "MaxKeys": min(limit, 1000),
                }
                if effective_prefix:
                    skip_kwargs["Prefix"] = effective_prefix
                if delimiter:
                    skip_kwargs["Delimiter"] = delimiter
                if continuation_token:
                    skip_kwargs["ContinuationToken"] = continuation_token

                skip_response = s3_client.list_objects_v2(**skip_kwargs)
                continuation_token = skip_response.get("NextContinuationToken")

                # If no more pages, return empty result
                if not continuation_token:
                    return S3ListFilesResult(
                        files=[],
                        folders=[],
                        page=page,
                        limit=limit,
                        total_count=total_count,
                        total_pages=total_pages,
                    )

        # Build list_objects_v2 parameters for the target page
        list_kwargs = {
            "Bucket": self.bucket_name,
            "MaxKeys": min(limit, 1000),
        }

        if effective_prefix:
            list_kwargs["Prefix"] = effective_prefix

        if delimiter:
            list_kwargs["Delimiter"] = delimiter

        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token

        response = s3_client.list_objects_v2(**list_kwargs)

        # Parse files
        files = []
        for obj in response.get("Contents", []):
            key = obj.get("Key", "")
            # Skip if the key is just the prefix itself (folder marker)
            if key == effective_prefix:
                continue
            # Extract filename from key
            name = key.rsplit("/", 1)[-1] if "/" in key else key
            if not name:  # Skip empty names (folder markers)
                continue
            files.append(
                {
                    "key": key,
                    "name": name,
                    "size": obj.get("Size"),
                    "last_modified": obj.get("LastModified"),
                    "content_type": mimetypes.guess_type(name)[0],  # Infer from extension
                }
            )

        # Parse folders (CommonPrefixes)
        folders = []
        for prefix_obj in response.get("CommonPrefixes", []):
            folder_prefix = prefix_obj.get("Prefix", "")
            # Extract folder name (remove trailing slash for display)
            folder_name = folder_prefix.rstrip("/").rsplit("/", 1)[-1]
            if folder_name:
                # Check if folder is empty (has any contents)
                # Do a quick check with MaxKeys=1
                check_response = s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=folder_prefix,
                    MaxKeys=1,
                )
                is_empty = check_response.get("KeyCount", 0) == 0
                folders.append(
                    {
                        "prefix": folder_prefix,
                        "name": folder_name,
                        "is_empty": is_empty,
                    }
                )

        return S3ListFilesResult(
            files=files,
            folders=folders,
            page=page,
            limit=limit,
            total_count=total_count,
            total_pages=total_pages,
        )

    def file(self, key: str) -> "S3Content":
        """Create a content reference for a specific file.

        Args:
            key: The S3 object key (path to file).

        Returns:
            S3Content configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import S3Content

        return S3Content(
            bucket_name=self.bucket_name,
            key=key,
            config_id=self.id,
        )

    def folder(self, prefix: str) -> "S3Content":
        """Create a content reference for a folder (prefix).

        Args:
            prefix: The S3 prefix (folder path).

        Returns:
            S3Content configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import S3Content

        return S3Content(
            bucket_name=self.bucket_name,
            prefix=prefix,
            config_id=self.id,
        )


class GcsConfig(RemoteContentConfig):
    """Configuration for Google Cloud Storage content source."""

    bucket_name: str
    project: Optional[str] = None
    credentials_path: Optional[str] = None
    prefix: Optional[str] = None

    def file(self, blob_name: str) -> "GCSContent":
        """Create a content reference for a specific file.

        Args:
            blob_name: The GCS blob name (path to file).

        Returns:
            GCSContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GCSContent

        return GCSContent(
            bucket_name=self.bucket_name,
            blob_name=blob_name,
            config_id=self.id,
        )

    def folder(self, prefix: str) -> "GCSContent":
        """Create a content reference for a folder (prefix).

        Args:
            prefix: The GCS prefix (folder path).

        Returns:
            GCSContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GCSContent

        return GCSContent(
            bucket_name=self.bucket_name,
            prefix=prefix,
            config_id=self.id,
        )


class SharePointConfig(RemoteContentConfig):
    """Configuration for SharePoint content source."""

    tenant_id: str
    client_id: str
    client_secret: str
    hostname: str
    site_path: Optional[str] = None
    site_id: Optional[str] = None  # Full site ID (e.g., "contoso.sharepoint.com,guid1,guid2")
    folder_path: Optional[str] = None

    def file(self, file_path: str, site_path: Optional[str] = None) -> "SharePointContent":
        """Create a content reference for a specific file.

        Args:
            file_path: Path to the file in SharePoint.
            site_path: Optional site path override.

        Returns:
            SharePointContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import SharePointContent

        return SharePointContent(
            config_id=self.id,
            file_path=file_path,
            site_path=site_path or self.site_path,
        )

    def folder(self, folder_path: str, site_path: Optional[str] = None) -> "SharePointContent":
        """Create a content reference for a folder.

        Args:
            folder_path: Path to the folder in SharePoint.
            site_path: Optional site path override.

        Returns:
            SharePointContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import SharePointContent

        return SharePointContent(
            config_id=self.id,
            folder_path=folder_path,
            site_path=site_path or self.site_path,
        )

    def _get_access_token(self) -> Optional[str]:
        """Get an access token for Microsoft Graph API."""
        try:
            from msal import ConfidentialClientApplication  # type: ignore
        except ImportError:
            raise ImportError("The `msal` package is not installed. Please install it via `pip install msal`.")

        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        app = ConfidentialClientApplication(
            self.client_id,
            authority=authority,
            client_credential=self.client_secret,
        )

        scopes = ["https://graph.microsoft.com/.default"]
        result = app.acquire_token_for_client(scopes=scopes)

        if "access_token" in result:
            return result["access_token"]
        return None

    def _get_site_id(self, access_token: str) -> Optional[str]:
        """Get the SharePoint site ID."""
        import httpx

        if self.site_id:
            return self.site_id

        if self.site_path:
            url = f"https://graph.microsoft.com/v1.0/sites/{self.hostname}:/{self.site_path}"
        else:
            url = f"https://graph.microsoft.com/v1.0/sites/{self.hostname}"

        response = httpx.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if response.status_code == 200:
            return response.json().get("id")
        return None

    def list_files(
        self,
        prefix: Optional[str] = None,
        delimiter: str = "/",
        limit: int = 100,
        page: int = 1,
    ) -> ListFilesResult:
        """List files and folders in SharePoint with pagination.

        Args:
            prefix: Path within the document library (e.g., "Shared Documents/Reports/")
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request
            page: Page number (1-indexed)

        Returns:
            ListFilesResult with files, folders, and pagination info
        """
        import httpx

        access_token = self._get_access_token()
        if not access_token:
            raise ValueError("Failed to acquire SharePoint access token")

        site_id = self._get_site_id(access_token)
        if not site_id:
            raise ValueError("Failed to get SharePoint site ID")

        # Use provided prefix or fall back to config folder_path
        folder_path = prefix if prefix is not None else (self.folder_path or "")

        # Build the Graph API URL for listing drive items
        headers = {"Authorization": f"Bearer {access_token}"}

        if folder_path:
            # List items in a specific folder
            encoded_path = folder_path.strip("/")
            url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root:/{encoded_path}:/children"
        else:
            # List items at root
            url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive/root/children"

        all_files = []
        folders = []

        # Fetch all items (Graph API paging)
        while url:
            response = httpx.get(url, headers=headers)
            if response.status_code != 200:
                raise ValueError(f"SharePoint API error: {response.status_code} - {response.text}")

            data = response.json()
            for item in data.get("value", []):
                if "folder" in item:
                    # It's a folder
                    folder_name = item.get("name", "")
                    folder_prefix = f"{folder_path.rstrip('/')}/{folder_name}/" if folder_path else f"{folder_name}/"
                    folders.append(
                        {
                            "prefix": folder_prefix,
                            "name": folder_name,
                            "is_empty": item.get("folder", {}).get("childCount", 0) == 0,
                        }
                    )
                elif "file" in item:
                    # It's a file
                    name = item.get("name", "")
                    key = f"{folder_path.rstrip('/')}/{name}" if folder_path else name
                    all_files.append(
                        {
                            "key": key,
                            "name": name,
                            "size": item.get("size"),
                            "last_modified": item.get("lastModifiedDateTime"),
                            "content_type": item.get("file", {}).get("mimeType") or mimetypes.guess_type(name)[0],
                        }
                    )

            # Check for next page
            url = data.get("@odata.nextLink")

        # Calculate pagination
        total_count = len(all_files)
        total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

        # Get files for the requested page
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_files = all_files[start_idx:end_idx]

        # Only include folders on first page
        if page > 1:
            folders = []

        return ListFilesResult(
            files=page_files,
            folders=folders,
            page=page,
            limit=limit,
            total_count=total_count,
            total_pages=total_pages,
        )


class GitHubConfig(RemoteContentConfig):
    """Configuration for GitHub content source."""

    repo: str
    token: Optional[str] = None
    branch: Optional[str] = None
    path: Optional[str] = None

    def file(self, file_path: str, branch: Optional[str] = None) -> "GitHubContent":
        """Create a content reference for a specific file.

        Args:
            file_path: Path to the file in the repository.
            branch: Optional branch override.

        Returns:
            GitHubContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return GitHubContent(
            config_id=self.id,
            file_path=file_path,
            branch=branch or self.branch,
        )

    def folder(self, folder_path: str, branch: Optional[str] = None) -> "GitHubContent":
        """Create a content reference for a folder.

        Args:
            folder_path: Path to the folder in the repository.
            branch: Optional branch override.

        Returns:
            GitHubContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import GitHubContent

        return GitHubContent(
            config_id=self.id,
            folder_path=folder_path,
            branch=branch or self.branch,
        )

    def list_files(
        self,
        prefix: Optional[str] = None,
        delimiter: str = "/",
        limit: int = 100,
        page: int = 1,
    ) -> ListFilesResult:
        """List files and folders in a GitHub repository with pagination.

        Args:
            prefix: Path within the repository (e.g., "docs/api/")
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request
            page: Page number (1-indexed)

        Returns:
            ListFilesResult with files, folders, and pagination info
        """
        import httpx

        headers = {"Accept": "application/vnd.github.v3+json"}
        if self.token:
            headers["Authorization"] = f"token {self.token}"

        # Get the branch (default to main)
        branch = self.branch or "main"

        # Use provided prefix or fall back to config path
        path = prefix.rstrip("/") if prefix else (self.path.rstrip("/") if self.path else "")

        # Build the GitHub API URL
        url = f"https://api.github.com/repos/{self.repo}/contents/{path}"
        if branch:
            url += f"?ref={branch}"

        response = httpx.get(url, headers=headers)

        if response.status_code == 404:
            return ListFilesResult(files=[], folders=[], page=page, limit=limit, total_count=0, total_pages=0)

        if response.status_code != 200:
            raise ValueError(f"GitHub API error: {response.status_code} - {response.text}")

        items = response.json()
        if not isinstance(items, list):
            # Single file was returned
            items = [items]

        all_files = []
        folders = []

        for item in items:
            item_type = item.get("type")
            name = item.get("name", "")
            item_path = item.get("path", "")

            if item_type == "dir":
                folder_prefix = f"{item_path}/"
                folders.append(
                    {
                        "prefix": folder_prefix,
                        "name": name,
                        "is_empty": False,  # GitHub doesn't tell us this
                    }
                )
            elif item_type == "file":
                all_files.append(
                    {
                        "key": item_path,
                        "name": name,
                        "size": item.get("size"),
                        "last_modified": None,  # GitHub contents API doesn't return this
                        "content_type": mimetypes.guess_type(name)[0],
                    }
                )

        # Calculate pagination
        total_count = len(all_files)
        total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

        # Get files for the requested page
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_files = all_files[start_idx:end_idx]

        # Only include folders on first page
        if page > 1:
            folders = []

        return ListFilesResult(
            files=page_files,
            folders=folders,
            page=page,
            limit=limit,
            total_count=total_count,
            total_pages=total_pages,
        )


class AzureBlobConfig(RemoteContentConfig):
    """Configuration for Azure Blob Storage content source.

    Uses Azure AD client credentials flow for authentication.

    Required Azure AD App Registration permissions:
        - Storage Blob Data Reader (or Contributor) role on the storage account

    Example:
        ```python
        config = AzureBlobConfig(
            id="company-docs",
            name="Company Documents",
            tenant_id=os.getenv("AZURE_TENANT_ID"),
            client_id=os.getenv("AZURE_CLIENT_ID"),
            client_secret=os.getenv("AZURE_CLIENT_SECRET"),
            storage_account=os.getenv("AZURE_STORAGE_ACCOUNT_NAME"),
            container=os.getenv("AZURE_CONTAINER_NAME"),
        )
        ```
    """

    tenant_id: str
    client_id: str
    client_secret: str
    storage_account: str
    container: str
    prefix: Optional[str] = None

    def file(self, blob_name: str) -> "AzureBlobContent":
        """Create a content reference for a specific blob (file).

        Args:
            blob_name: The blob name (path to file in container).

        Returns:
            AzureBlobContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import AzureBlobContent

        return AzureBlobContent(
            config_id=self.id,
            blob_name=blob_name,
        )

    def folder(self, prefix: str) -> "AzureBlobContent":
        """Create a content reference for a folder (prefix).

        Args:
            prefix: The blob prefix (folder path).

        Returns:
            AzureBlobContent configured with this source's credentials.
        """
        from agno.knowledge.remote_content.remote_content import AzureBlobContent

        return AzureBlobContent(
            config_id=self.id,
            prefix=prefix,
        )

    def list_files(
        self,
        prefix: Optional[str] = None,
        delimiter: str = "/",
        limit: int = 100,
        page: int = 1,
    ) -> ListFilesResult:
        """List files and folders in this Azure Blob container with pagination.

        Args:
            prefix: Path prefix to filter blobs (e.g., "reports/2024/")
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request (1-1000)
            page: Page number (1-indexed)

        Returns:
            ListFilesResult with files, folders, and pagination info
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
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

        blob_service = BlobServiceClient(
            account_url=f"https://{self.storage_account}.blob.core.windows.net",
            credential=credential,
        )

        container_client = blob_service.get_container_client(self.container)

        # Use provided prefix or fall back to config prefix
        effective_prefix = prefix if prefix is not None else (self.prefix or "")

        # List all blobs to count and paginate
        all_files = []
        folders_set: set = set()

        blobs = container_client.walk_blobs(name_starts_with=effective_prefix, delimiter=delimiter)

        for blob in blobs:
            if hasattr(blob, "prefix"):
                # This is a virtual folder (BlobPrefix)
                folder_prefix = blob.prefix
                folder_name = folder_prefix.rstrip("/").rsplit("/", 1)[-1]
                if folder_name:
                    folders_set.add((folder_prefix, folder_name))
            else:
                # This is a blob (file)
                key = blob.name
                if key == effective_prefix:
                    continue
                name = key.rsplit("/", 1)[-1] if "/" in key else key
                if not name:
                    continue
                all_files.append(
                    {
                        "key": key,
                        "name": name,
                        "size": blob.size,
                        "last_modified": blob.last_modified,
                        "content_type": mimetypes.guess_type(name)[0],
                    }
                )

        # Calculate pagination
        total_count = len(all_files)
        total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

        # Get files for the requested page
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        page_files = all_files[start_idx:end_idx]

        # Build folders list (only on first page)
        folders = []
        if page == 1:
            for folder_prefix, folder_name in sorted(folders_set):
                folders.append(
                    {
                        "prefix": folder_prefix,
                        "name": folder_name,
                        "is_empty": False,  # Azure doesn't have cheap empty check
                    }
                )

        return ListFilesResult(
            files=page_files,
            folders=folders,
            page=page,
            limit=limit,
            total_count=total_count,
            total_pages=total_pages,
        )
