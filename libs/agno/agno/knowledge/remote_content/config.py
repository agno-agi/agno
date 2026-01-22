from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import (
        GCSContent,
        GitHubContent,
        S3Content,
        SharePointContent,
    )


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
