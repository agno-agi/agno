from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agno.knowledge.remote_content.base import BaseStorageConfig

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import AzureBlobContent


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
