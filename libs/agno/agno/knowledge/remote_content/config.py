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


class S3ListFilesResult:
    """Result of listing files from S3."""

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
