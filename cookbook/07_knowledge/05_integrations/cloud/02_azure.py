"""
Azure Integration: Blob Storage
=================================
Load files and folders from Azure Blob Storage containers into your Knowledge base.

Features:
- Load single files or entire prefixes (folders)
- Uses Azure AD client credentials for authentication

Requirements:
- Azure AD App Registration with Storage Blob Data Reader role
- Client ID, Client Secret, and Tenant ID

Environment Variables:
    AZURE_TENANT_ID            - Azure AD tenant ID
    AZURE_CLIENT_ID            - App registration client ID
    AZURE_CLIENT_SECRET        - App registration client secret
    AZURE_STORAGE_ACCOUNT_NAME - Storage account name
    AZURE_CONTAINER_NAME       - Container name
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import AzureBlobConfig
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

azure_blob = AzureBlobConfig(
    id="company-blob",
    name="Company Blob Storage",
    tenant_id=getenv("AZURE_TENANT_ID"),
    client_id=getenv("AZURE_CLIENT_ID"),
    client_secret=getenv("AZURE_CLIENT_SECRET"),
    storage_account=getenv("AZURE_STORAGE_ACCOUNT_NAME"),
    container=getenv("AZURE_CONTAINER_NAME"),
)

knowledge = Knowledge(
    name="Azure Blob Knowledge",
    vector_db=Qdrant(
        collection="azure_blob_knowledge",
        url="http://localhost:6333",
    ),
    content_sources=[azure_blob],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Single file
        print("\n" + "=" * 60)
        print("Azure Blob Storage: single file")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Report",
            remote_content=azure_blob.file("reports/annual-report.pdf"),
        )

        # Folder
        print("\n" + "=" * 60)
        print("Azure Blob Storage: folder")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="All Docs",
            remote_content=azure_blob.folder("documents/"),
        )

        results = knowledge.search("What were the annual results?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
