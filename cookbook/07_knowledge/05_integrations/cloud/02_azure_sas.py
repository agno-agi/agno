"""
Azure Integration: Blob Storage (SAS Token)
=============================================
Load files and folders from Azure Blob Storage containers using SAS token authentication.

Features:
- Load single files or entire prefixes (folders)
- Uses SAS (Shared Access Signature) token for authentication

Requirements:
- Azure Storage Account with a SAS token

Environment Variables:
    AZURE_SAS_TOKEN            - SAS token
    AZURE_STORAGE_ACCOUNT_NAME - Storage account name
    AZURE_CONTAINER_NAME       - Container name

Run `uv pip install azure-storage-blob` to install dependencies.
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import AzureBlobConfig
from agno.vectordb.chroma import ChromaDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

azure_blob = AzureBlobConfig(
    id="company-blob-sas",
    name="Company Blob Storage SAS",
    sas_token=getenv("AZURE_SAS_TOKEN"),
    storage_account=getenv("AZURE_STORAGE_ACCOUNT_NAME"),
    container=getenv("AZURE_CONTAINER_NAME"),
)

knowledge = Knowledge(
    name="Azure Blob Knowledge (SAS)",
    vector_db=ChromaDb(
        collection="azure_blob_knowledge_sas",
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
        print("Azure Blob Storage (SAS): single file")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Report",
            remote_content=azure_blob.file("reports/annual-report.pdf"),
        )

        # Folder
        print("\n" + "=" * 60)
        print("Azure Blob Storage (SAS): folder")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="All Docs",
            remote_content=azure_blob.folder("documents/"),
        )

        results = knowledge.search("What were the annual results?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
