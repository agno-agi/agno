"""
SharePoint Content Source for Knowledge
========================================

Load files and folders from SharePoint document libraries into your Knowledge base.
Uses Microsoft Graph API with OAuth2 client credentials flow.

Features:
- Load single files or entire folders recursively
- Supports any SharePoint Online site
- Automatic file type detection and reader selection
- Rich metadata stored for each file (site, path, filename)

Requirements:
- Azure AD App Registration with:
  - Application (client) ID
  - Client secret
  - API permissions: Sites.Read.All (Application)
- SharePoint site ID or site path

Setup:
    1. Register an app in Azure AD (portal.azure.com)
    2. Add API permission: Microsoft Graph > Sites.Read.All (Application)
    3. Grant admin consent
    4. Create a client secret
    5. Set environment variables (see below)

Environment Variables:
    SHAREPOINT_TENANT_ID    - Azure AD tenant ID
    SHAREPOINT_CLIENT_ID    - App registration client ID
    SHAREPOINT_CLIENT_SECRET - App registration client secret
    SHAREPOINT_HOSTNAME     - e.g., "contoso.sharepoint.com"
    SHAREPOINT_SITE_ID      - Full site ID (hostname,guid,guid format)

Run this cookbook:
    python cookbook/07_knowledge/cloud/sharepoint.py
"""

from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import SharePointConfig
from agno.vectordb.pgvector import PgVector

# Configure SharePoint content source
# All credentials should come from environment variables
sharepoint_config = SharePointConfig(
    id="company-docs",
    name="Company Documents",
    tenant_id=getenv("SHAREPOINT_TENANT_ID"),
    client_id=getenv("SHAREPOINT_CLIENT_ID"),
    client_secret=getenv("SHAREPOINT_CLIENT_SECRET"),
    hostname=getenv("SHAREPOINT_HOSTNAME"),  # e.g., "contoso.sharepoint.com"
    # Option 1: Provide site_id directly (recommended, faster)
    site_id=getenv("SHAREPOINT_SITE_ID"),  # e.g., "contoso.sharepoint.com,guid1,guid2"
    # Option 2: Or provide site_path and let the API look up the site ID
    # site_path="/sites/documents",
)

# Create Knowledge with SharePoint as a content source
knowledge = Knowledge(
    name="SharePoint Knowledge",
    vector_db=PgVector(
        table_name="sharepoint_knowledge",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    ),
    content_sources=[sharepoint_config],
)

if __name__ == "__main__":
    # Insert a single file from SharePoint
    print("Inserting single file from SharePoint...")
    knowledge.insert(
        name="Q1 Report",
        remote_content=sharepoint_config.file("Shared Documents/Reports/q1-2024.pdf"),
    )

    # Insert an entire folder (recursive)
    print("Inserting folder from SharePoint...")
    knowledge.insert(
        name="Policy Documents",
        remote_content=sharepoint_config.folder("Shared Documents/Policies"),
    )
