"""
Azure Integration: Blob Storage and SharePoint
================================================
Load content from Azure Blob Storage containers and SharePoint sites.

Azure Blob Storage:
- Load files/folders from Azure Storage containers
- Uses Azure AD client credentials for authentication

SharePoint:
- Load files/folders from SharePoint document libraries
- Uses Azure AD client credentials with Sites.Read.All permission

Requirements:
- Azure AD App Registration with appropriate permissions
- Client ID, Client Secret, and Tenant ID

Environment Variables:
    AZURE_TENANT_ID            - Azure AD tenant ID
    AZURE_CLIENT_ID            - App registration client ID
    AZURE_CLIENT_SECRET        - App registration client secret
    AZURE_STORAGE_ACCOUNT_NAME - Storage account (for Blob)
    AZURE_CONTAINER_NAME       - Container name (for Blob)
    SHAREPOINT_HOSTNAME        - SharePoint hostname (e.g. contoso.sharepoint.com)
"""

from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import AzureBlobConfig, SharePointConfig
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# --- Azure Blob Storage ---
azure_blob = AzureBlobConfig(
    id="company-blob",
    name="Company Blob Storage",
    tenant_id=getenv("AZURE_TENANT_ID"),
    client_id=getenv("AZURE_CLIENT_ID"),
    client_secret=getenv("AZURE_CLIENT_SECRET"),
    storage_account=getenv("AZURE_STORAGE_ACCOUNT_NAME"),
    container=getenv("AZURE_CONTAINER_NAME"),
)

# --- SharePoint ---
sharepoint = SharePointConfig(
    id="company-sharepoint",
    name="Company SharePoint",
    tenant_id=getenv("AZURE_TENANT_ID"),
    client_id=getenv("AZURE_CLIENT_ID"),
    client_secret=getenv("AZURE_CLIENT_SECRET"),
    hostname=getenv("SHAREPOINT_HOSTNAME"),
)

knowledge = Knowledge(
    name="Azure Knowledge",
    vector_db=Qdrant(
        collection="azure_knowledge",
        url="http://localhost:6333",
    ),
    content_sources=[azure_blob, sharepoint],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Blob Storage: single file ---
    print("\n" + "=" * 60)
    print("Azure Blob Storage: single file")
    print("=" * 60 + "\n")

    knowledge.insert(
        name="Report",
        remote_content=azure_blob.file("reports/annual-report.pdf"),
    )

    # --- Blob Storage: folder ---
    print("\n" + "=" * 60)
    print("Azure Blob Storage: folder")
    print("=" * 60 + "\n")

    knowledge.insert(
        name="All Docs",
        remote_content=azure_blob.folder("documents/"),
    )

    # --- SharePoint: file ---
    print("\n" + "=" * 60)
    print("SharePoint: single file")
    print("=" * 60 + "\n")

    knowledge.insert(
        name="Policy Doc",
        remote_content=sharepoint.file("Shared Documents/policy.pdf"),
    )
