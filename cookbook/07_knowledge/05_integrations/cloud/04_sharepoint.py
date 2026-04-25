"""
SharePoint Integration
=======================
Load files and folders from SharePoint document libraries into your Knowledge base.

Features:
- Load single files or entire folders from SharePoint
- Uses Azure AD client credentials with Sites.Read.All permission

Requirements:
- Azure AD App Registration with Sites.Read.All permission
- Client ID, Client Secret, and Tenant ID

Environment Variables:
    AZURE_TENANT_ID     - Azure AD tenant ID
    AZURE_CLIENT_ID     - App registration client ID
    AZURE_CLIENT_SECRET - App registration client secret
    SHAREPOINT_HOSTNAME - SharePoint hostname (e.g. contoso.sharepoint.com)
"""

import asyncio
from os import getenv

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import SharePointConfig
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

sharepoint = SharePointConfig(
    id="company-sharepoint",
    name="Company SharePoint",
    tenant_id=getenv("AZURE_TENANT_ID"),
    client_id=getenv("AZURE_CLIENT_ID"),
    client_secret=getenv("AZURE_CLIENT_SECRET"),
    hostname=getenv("SHAREPOINT_HOSTNAME"),
)

knowledge = Knowledge(
    name="SharePoint Knowledge",
    vector_db=Qdrant(
        collection="sharepoint_knowledge",
        url="http://localhost:6333",
    ),
    content_sources=[sharepoint],
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # Single file
        print("\n" + "=" * 60)
        print("SharePoint: single file")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Policy Doc",
            remote_content=sharepoint.file("Shared Documents/policy.pdf"),
        )

        # Folder
        print("\n" + "=" * 60)
        print("SharePoint: folder")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="All Shared Docs",
            remote_content=sharepoint.folder("Shared Documents/"),
        )

        results = knowledge.search("What is the policy?")
        for doc in results:
            print("- %s" % doc.name)

    asyncio.run(main())
