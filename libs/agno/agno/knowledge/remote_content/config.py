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


class BaseStorageConfig(BaseModel):
    """Base configuration for remote content sources."""

    id: str
    name: str
    metadata: Optional[dict] = None

    model_config = ConfigDict(extra="allow")


class S3Config(BaseStorageConfig):
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
    ) -> ListFilesResult:
        """List files and folders in this S3 source with pagination.

        Uses S3's native continuation-token pagination to avoid loading all
        objects into memory. Only fetches the objects needed for the requested
        page (plus objects to skip for earlier pages).

        Args:
            prefix: Path prefix to filter files (e.g., "reports/2024/").
                    Overrides the config's prefix when provided.
            delimiter: Folder delimiter (default "/")
            limit: Max files to return per request (1-1000, clamped)
            page: Page number (1-indexed)

        Returns:
            ListFilesResult with files, folders, and pagination info
        """
        try:
            import boto3
        except ImportError:
            raise ImportError("The `boto3` package is not installed. Please install it via `pip install boto3`.")

        limit = max(1, min(limit, 1000))

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

        # Number of file objects to skip for pages before the requested one
        skip_count = (page - 1) * limit
        skipped = 0
        collected: list = []
        folders: list = []
        folders_seen = False
        total_count = 0
        has_more = False

        # Use list_objects_v2 directly with continuation tokens to avoid
        # loading all objects into memory.
        list_kwargs: dict = {"Bucket": self.bucket_name, "MaxKeys": 1000}
        if effective_prefix:
            list_kwargs["Prefix"] = effective_prefix
        if delimiter:
            list_kwargs["Delimiter"] = delimiter

        while True:
            response = s3_client.list_objects_v2(**list_kwargs)

            # Collect folders from first response only
            if not folders_seen:
                for prefix_obj in response.get("CommonPrefixes", []):
                    folder_prefix = prefix_obj.get("Prefix", "")
                    folder_name = folder_prefix.rstrip("/").rsplit("/", 1)[-1]
                    if folder_name:
                        folders.append(
                            {
                                "prefix": folder_prefix,
                                "name": folder_name,
                                "is_empty": False,
                            }
                        )
                folders_seen = True

            # Process file objects
            for obj in response.get("Contents", []):
                key = obj.get("Key", "")
                if key == effective_prefix:
                    continue
                name = key.rsplit("/", 1)[-1] if "/" in key else key
                if not name:
                    continue

                total_count += 1

                # Skip objects for earlier pages
                if skipped < skip_count:
                    skipped += 1
                    continue

                # Collect objects for the requested page
                if len(collected) < limit:
                    collected.append(
                        {
                            "key": key,
                            "name": name,
                            "size": obj.get("Size"),
                            "last_modified": obj.get("LastModified"),
                            "content_type": mimetypes.guess_type(name)[0],
                        }
                    )

            # Check if there are more pages from S3
            if response.get("IsTruncated"):
                list_kwargs["ContinuationToken"] = response["NextContinuationToken"]
                # If we already have enough items, count remaining for total_count
                # but cap the counting to avoid iterating forever on huge buckets
                if len(collected) >= limit:
                    has_more = True
                    break
            else:
                break

        # If we broke out early, we don't know the exact total —
        # indicate there are more pages available
        if has_more:
            # We know at least this many exist; signal "more available"
            total_pages = page + 1
        else:
            total_pages = (total_count + limit - 1) // limit if limit > 0 else 0

        # Only include folders on first page
        if page > 1:
            folders = []

        return ListFilesResult(
            files=collected,
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


class GcsConfig(BaseStorageConfig):
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


class SharePointConfig(BaseStorageConfig):
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


class GitHubConfig(BaseStorageConfig):
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


class LocalStorageConfig(BaseStorageConfig):
    """Configuration for local filesystem storage.

    Stores raw content files to a local directory. Useful for development
    and testing without needing cloud credentials.

    Example:
        ```python
        config = LocalStorageConfig(
            id="local-raw",
            name="Local Raw Storage",
            base_path="/tmp/knowledge-backup-storage",
        )
        ```
    """

    base_path: str


class AzureBlobConfig(BaseStorageConfig):
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
