from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agno.knowledge.remote_content.base import BaseStorageConfig

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import SharePointContent


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

        try:
            response = httpx.get(url, headers={"Authorization": f"Bearer {access_token}"})
            if response.status_code == 200:
                return response.json().get("id")
        except httpx.HTTPError:
            pass
        return None
