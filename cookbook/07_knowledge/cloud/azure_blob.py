"""
Azure Blob Storage Content Source for Knowledge
================================================

Load files and folders from Azure Blob Storage containers into your Knowledge base.
Uses Azure AD client credentials flow for authentication.

Features:
- Load single blobs or entire prefixes (folders) recursively
- Supports any Azure Storage Account
- Automatic file type detection and reader selection
- Rich metadata stored for each file (storage account, container, path)

Requirements:
- Azure AD App Registration with:
  - Application (client) ID
  - Client secret
  - Storage Blob Data Reader role on the storage account
- Storage account name and container name

Setup:
    1. Register an app in Azure AD (portal.azure.com)
    2. Assign "Storage Blob Data Reader" role to the app on your storage account
    3. Create a client secret
    4. Set environment variables (see below)

Environment Variables:
    AZURE_TENANT_ID           - Azure AD tenant ID
    AZURE_CLIENT_ID           - App registration client ID
    AZURE_CLIENT_SECRET       - App registration client secret
    AZURE_STORAGE_ACCOUNT_NAME - Storage account name (without .blob.core.windows.net)
    AZURE_CONTAINER_NAME      - Container name

Run this cookbook:
    python cookbook/07_knowledge/cloud/azure_blob.py
"""

from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import AzureBlobConfig
from agno.vectordb.pgvector import PgVector

# Configure Azure Blob Storage content source
# All credentials should come from environment variables
azure_config = AzureBlobConfig(
    id="company-docs",
    name="Company Documents",
    tenant_id=getenv("AZURE_TENANT_ID"),
    client_id=getenv("AZURE_CLIENT_ID"),
    client_secret=getenv("AZURE_CLIENT_SECRET"),
    storage_account=getenv("AZURE_STORAGE_ACCOUNT_NAME"),
    container=getenv("AZURE_CONTAINER_NAME"),
)

# Create Knowledge with Azure Blob Storage as a content source
knowledge = Knowledge(
    name="Azure Blob Knowledge",
    vector_db=PgVector(
        table_name="azure_blob_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    content_sources=[azure_config],
)

if __name__ == "__main__":
    # Insert a single file from Azure Blob Storage
    print("Inserting single file from Azure Blob Storage...")
    knowledge.insert(
        name="DeepSeek Paper",
        remote_content=azure_config.file("DeepSeek_R1.pdf"),
    )

    # Insert an entire folder (prefix)
    print("Inserting folder from Azure Blob Storage...")
    knowledge.insert(
        name="Research Papers",
        remote_content=azure_config.folder("testfolder/"),
    )

    # Search the knowledge base
    print("Searching knowledge base...")
    results = knowledge.search("What is DeepSeek?")
    for doc in results:
        print(f"- {doc.name}: {doc.content[:100]}...")
