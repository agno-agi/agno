from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from pydantic import model_validator

from agno.knowledge.remote_content.base import BaseStorageConfig

if TYPE_CHECKING:
    from agno.knowledge.remote_content.remote_content import AzureBlobContent


class AzureBlobConfig(BaseStorageConfig):
    """Configuration for Azure Blob Storage content source.

    Supports two authentication methods:

    1. **Service Principal (Azure AD client credentials flow)**:
       Provide ``tenant_id``, ``client_id``, and ``client_secret``.
       Requires Storage Blob Data Reader (or higher) role on the storage account.

    2. **SAS token (Shared Access Signature)**:
       Provide ``sas_token`` — the query-string portion of a SAS URL
       (everything after the ``?``).

    Examples:
        Service Principal::

            config = AzureBlobConfig(
                id="company-docs",
                name="Company Documents",
                tenant_id=os.getenv("AZURE_TENANT_ID"),
                client_id=os.getenv("AZURE_CLIENT_ID"),
                client_secret=os.getenv("AZURE_CLIENT_SECRET"),
                storage_account=os.getenv("AZURE_STORAGE_ACCOUNT_NAME"),
                container=os.getenv("AZURE_CONTAINER_NAME"),
            )

        SAS token::

            config = AzureBlobConfig(
                id="company-docs",
                name="Company Documents",
                sas_token=os.getenv("AZURE_SAS_TOKEN"),
                storage_account=os.getenv("AZURE_STORAGE_ACCOUNT_NAME"),
                container=os.getenv("AZURE_CONTAINER_NAME"),
            )
    """

    # Service Principal fields (required together, or omit all for SAS auth)
    tenant_id: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None

    # SAS token field (alternative to Service Principal)
    sas_token: Optional[str] = None

    storage_account: str
    container: str
    prefix: Optional[str] = None

    @model_validator(mode="after")
    def _validate_auth(self) -> "AzureBlobConfig":
        sp_fields = (self.tenant_id, self.client_id, self.client_secret)
        has_sp = all(f is not None for f in sp_fields)
        has_partial_sp = any(f is not None for f in sp_fields) and not has_sp
        has_sas = self.sas_token is not None

        if has_sas and has_sp:
            raise ValueError(
                "Provide either Service Principal credentials (tenant_id, client_id, client_secret) "
                "or a sas_token, not both."
            )
        if has_partial_sp:
            if has_sas:
                raise ValueError(
                    "Provide either a sas_token or complete Service Principal credentials "
                    "(tenant_id, client_id, client_secret), not a mix of both."
                )
            raise ValueError(
                "Incomplete Service Principal credentials: all of tenant_id, client_id, and client_secret are required."
            )
        if not has_sp and not has_sas:
            raise ValueError(
                "Authentication required: provide either Service Principal credentials "
                "(tenant_id, client_id, client_secret) or a sas_token."
            )
        return self

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
