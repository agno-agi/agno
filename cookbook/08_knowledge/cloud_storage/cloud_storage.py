"""
Content Sources for Knowledge — Developer Experience Design
============================================================

This cookbook demonstrates the THEORETICAL API for adding content from various
remote sources (S3, GCS, SharePoint, GitHub, etc.) to a Knowledge base.

NOTE: This is a DX design document. The classes shown here are NOT YET IMPLEMENTED.
      Once the DX is finalized, implementation will follow.

Key Concepts:
- ContentSource: Base class for any remote content source
- Each source type has its own class: S3ContentSource, GCSContentSource, etc.
- Sources are registered on Knowledge via `content_sources` parameter
- UI can list files from sources, users select which to add
- `add_from_source()` is the primary method for adding content from sources
"""

import asyncio
from typing import List

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# =============================================================================
# IMPORTS (theoretical - not yet implemented)
# =============================================================================

from agno.knowledge.sources import (
    # Base class
    ContentSource,
    StorageFile,
    # Cloud storage sources
    S3ContentSource,
    S3Credentials,
    GCSContentSource,
    GCSCredentials,
    # Collaboration sources
    SharePointContentSource,
    SharePointCredentials,
    GitHubContentSource,
    GitHubCredentials,
)

# =============================================================================
# SECTION 1: S3 Content Source
# =============================================================================

# -----------------------------------------------------------------------------
# Level 1: Simple - Uses environment variables or IAM role for credentials
# -----------------------------------------------------------------------------

s3_simple = S3ContentSource(
    id="company-docs",
    name="Company Documents",
    bucket_name="acme-company-docs",
)

# -----------------------------------------------------------------------------
# Level 2: Inline credentials - Quick setup for development
# -----------------------------------------------------------------------------

s3_with_inline_creds = S3ContentSource(
    id="company-docs",
    name="Company Documents",
    bucket_name="acme-company-docs",
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    region="us-west-2",
)

# -----------------------------------------------------------------------------
# Level 3: Credential object - Full control, reusable across sources
# -----------------------------------------------------------------------------

s3_credentials = S3Credentials(
    access_key="AKIAIOSFODNN7EXAMPLE",
    secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    session_token="FwoGZXIvYXdzEBY...",  # Optional: for temporary credentials
    region="us-west-2",
)

s3_with_credential_object = S3ContentSource(
    id="company-docs",
    name="Company Documents",
    description="All company documents stored in S3",
    bucket_name="acme-company-docs",
    credentials=s3_credentials,
    prefix="documents/",  # Optional: default prefix filter when listing files
)

# =============================================================================
# SECTION 2: GCS Content Source
# =============================================================================

# Level 1: Simple - Uses Application Default Credentials (ADC)
gcs_simple = GCSContentSource(
    id="training-data",
    name="ML Training Data",
    bucket_name="acme-ml-training",
    project="acme-ml-project",
)

# Level 3: With service account credentials
gcs_credentials = GCSCredentials(
    service_account_path="/path/to/service-account.json",
    # OR: service_account_json='{"type": "service_account", ...}',
    project="acme-ml-project",
)

gcs_with_credentials = GCSContentSource(
    id="training-data",
    name="ML Training Data",
    bucket_name="acme-ml-training",
    credentials=gcs_credentials,
)

# =============================================================================
# SECTION 3: SharePoint Content Source
# =============================================================================

# SharePoint uses OAuth / App credentials for authentication

sharepoint_credentials = SharePointCredentials(
    tenant_id="your-tenant-id",
    client_id="your-app-client-id",
    client_secret="your-app-client-secret",
)

sharepoint_source = SharePointContentSource(
    id="company-sharepoint",
    name="Company SharePoint",
    description="Internal company documents on SharePoint",
    site_url="https://acme.sharepoint.com/sites/Engineering",
    # OR use site_id directly: site_id="site-guid-here",
    drive_name="Documents",  # Optional: specific document library
    credentials=sharepoint_credentials,
)

# =============================================================================
# SECTION 4: GitHub Content Source
# =============================================================================

# GitHub uses Personal Access Token or GitHub App credentials

github_credentials = GitHubCredentials(
    token="ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    # OR for GitHub App:
    # app_id="123456",
    # private_key_path="/path/to/private-key.pem",
    # installation_id="12345678",
)

github_source = GitHubContentSource(
    id="internal-docs",
    name="Internal Documentation",
    description="Documentation from private GitHub repo",
    repo="acme-corp/internal-docs",  # owner/repo format
    branch="main",  # Optional, defaults to main
    path="docs/",  # Optional: only list files under this path
    credentials=github_credentials,
)

# =============================================================================
# SECTION 5: Dict-based Configuration
# =============================================================================

# All content sources can also be configured via dictionaries.
# This is useful for config files, environment-based setup, or API payloads.

s3_as_dict = {
    "type": "s3",
    "id": "company-docs",
    "name": "Company Documents",
    "bucket_name": "acme-company-docs",
    "region": "us-west-2",
    # Credentials can be nested dict or omitted to use env vars
    "credentials": {
        "access_key": "AKIAIOSFODNN7EXAMPLE",
        "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    },
}

sharepoint_as_dict = {
    "type": "sharepoint",
    "id": "company-sharepoint",
    "name": "Company SharePoint",
    "site_url": "https://acme.sharepoint.com/sites/Engineering",
    "credentials": {
        "tenant_id": "your-tenant-id",
        "client_id": "your-app-client-id",
        "client_secret": "your-app-client-secret",
    },
}

github_as_dict = {
    "type": "github",
    "id": "internal-docs",
    "name": "Internal Documentation",
    "repo": "acme-corp/internal-docs",
    "branch": "main",
    "credentials": {
        "token": "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    },
}

# =============================================================================
# SECTION 6: Knowledge with Content Sources
# =============================================================================

# Database connections
contents_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
vector_db = PgVector(
    table_name="knowledge_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Create Knowledge with multiple content sources
knowledge = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    # Register content sources - mix of class instances and dicts
    content_sources=[
        # S3 bucket with IAM credentials (from env)
        S3ContentSource(
            id="s3-docs",
            name="S3 Documents",
            bucket_name="acme-company-docs",
        ),
        # GCS bucket
        GCSContentSource(
            id="gcs-data",
            name="GCS Training Data",
            bucket_name="acme-ml-data",
            project="acme-ml",
        ),
        # SharePoint (dict form)
        {
            "type": "sharepoint",
            "id": "sharepoint-eng",
            "name": "Engineering SharePoint",
            "site_url": "https://acme.sharepoint.com/sites/Engineering",
            "credentials": {
                "tenant_id": "xxx",
                "client_id": "xxx",
                "client_secret": "xxx",
            },
        },
        # GitHub (dict form)
        {
            "type": "github",
            "id": "github-docs",
            "name": "GitHub Documentation",
            "repo": "acme-corp/docs",
            "credentials": {"token": "ghp_xxx"},
        },
    ],
)

# =============================================================================
# SECTION 7: UI Workflow - List Sources and Files
# =============================================================================

# Step 1: Get all registered content sources (for UI dropdown)
sources = knowledge.get_content_sources()
# Returns: [
#     {"id": "s3-docs", "name": "S3 Documents", "type": "s3", "description": None},
#     {"id": "gcs-data", "name": "GCS Training Data", "type": "gcs", "description": None},
#     {"id": "sharepoint-eng", "name": "Engineering SharePoint", "type": "sharepoint", ...},
#     {"id": "github-docs", "name": "GitHub Documentation", "type": "github", ...},
# ]

# Step 2: User selects a source, list available files
files: List[StorageFile] = knowledge.list_source_files("s3-docs")
# Returns: [
#     StorageFile(key="reports/q1-2024.pdf", name="q1-2024.pdf", size=102400, last_modified="2024-01-15T10:30:00Z"),
#     StorageFile(key="reports/q2-2024.pdf", name="q2-2024.pdf", size=98304, last_modified="2024-04-15T14:20:00Z"),
#     StorageFile(key="policies/security.pdf", name="security.pdf", size=51200, last_modified="2024-02-01T09:00:00Z"),
# ]

# Step 3: List with prefix filter (for folder navigation in UI)
files_in_folder = knowledge.list_source_files("s3-docs", prefix="reports/")
# Returns only files under reports/

# Async versions available for all operations
async def list_files_example():
    files = await knowledge.list_source_files_async("s3-docs", prefix="reports/")
    return files

# =============================================================================
# SECTION 8: Adding Content from Sources
# =============================================================================

# -----------------------------------------------------------------------------
# Method 1: Add a single file from a source
# -----------------------------------------------------------------------------

# Sync version
knowledge.add_from_source(
    source_id="s3-docs",
    key="reports/q1-2024.pdf",
    # Optional overrides:
    name="Q1 2024 Financial Report",  # Defaults to filename from key
    description="Quarterly financial report for Q1 2024",
    metadata={"department": "finance", "year": "2024", "quarter": "Q1"},
)

# Async version
async def add_single_file():
    await knowledge.add_from_source_async(
        source_id="s3-docs",
        key="reports/q1-2024.pdf",
        name="Q1 2024 Financial Report",
        metadata={"department": "finance"},
    )

# -----------------------------------------------------------------------------
# Method 2: Add multiple files from a source (batch)
# -----------------------------------------------------------------------------

# User selected these files in the UI
selected_keys = [
    "reports/q1-2024.pdf",
    "reports/q2-2024.pdf",
    "policies/security.pdf",
]

# Sync version
knowledge.add_files_from_source(
    source_id="s3-docs",
    keys=selected_keys,
    metadata={"source": "s3", "batch_import": "true"},  # Applied to all files
)

# Async version
async def add_multiple_files():
    await knowledge.add_files_from_source_async(
        source_id="s3-docs",
        keys=selected_keys,
        metadata={"source": "s3"},
    )

# -----------------------------------------------------------------------------
# Method 3: Add from different sources
# -----------------------------------------------------------------------------

async def add_from_various_sources():
    # Add from S3
    await knowledge.add_from_source_async(
        source_id="s3-docs",
        key="reports/annual-2024.pdf",
    )

    # Add from SharePoint
    await knowledge.add_from_source_async(
        source_id="sharepoint-eng",
        key="Engineering/Architecture/system-design.docx",
    )

    # Add from GitHub
    await knowledge.add_from_source_async(
        source_id="github-docs",
        key="guides/onboarding.md",
    )

# =============================================================================
# SECTION 9: Advanced - Working with StorageFile objects
# =============================================================================

async def advanced_file_selection():
    """Example: Add all PDF files larger than 10KB from a source."""

    # List all files
    files = await knowledge.list_source_files_async("s3-docs")

    # Filter: only PDFs larger than 10KB
    pdf_files = [
        f for f in files
        if f.name.endswith(".pdf") and f.size and f.size > 10240
    ]

    # Add selected files
    keys = [f.key for f in pdf_files]
    await knowledge.add_files_from_source_async(
        source_id="s3-docs",
        keys=keys,
    )

# =============================================================================
# SECTION 10: Using with an Agent
# =============================================================================

# After adding content to knowledge, use it with an agent
agent = Agent(
    name="Knowledge Assistant",
    description="Assistant with access to company knowledge",
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# The agent can now search across all content added from various sources
agent.print_response("What are the key points from the Q1 2024 financial report?")
agent.print_response("Summarize our security policies")
agent.print_response("What does the system architecture look like?")

# =============================================================================
# SECTION 11: Complete Example - Full Workflow
# =============================================================================

async def complete_workflow():
    """
    Complete example showing the full workflow:
    1. Create knowledge with content sources
    2. List available sources
    3. List files from a source
    4. Add selected files
    5. Query with an agent
    """

    # 1. Create Knowledge with sources
    knowledge = Knowledge(
        name="My Knowledge Base",
        vector_db=PgVector(
            table_name="vectors",
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        ),
        content_sources=[
            S3ContentSource(
                id="my-s3",
                name="My S3 Bucket",
                bucket_name="my-bucket",
            ),
        ],
    )

    # 2. Get available sources (for UI)
    sources = knowledge.get_content_sources()
    print("Available sources:")
    for source in sources:
        print(f"  - {source['name']} ({source['type']})")

    # 3. List files from first source
    source_id = sources[0]["id"]
    files = await knowledge.list_source_files_async(source_id)
    print(f"\nFiles in {sources[0]['name']}:")
    for file in files[:10]:  # Show first 10
        print(f"  - {file.name} ({file.size} bytes)")

    # 4. Add some files
    if files:
        keys_to_add = [f.key for f in files[:3]]  # Add first 3 files
        await knowledge.add_files_from_source_async(
            source_id=source_id,
            keys=keys_to_add,
        )
        print(f"\nAdded {len(keys_to_add)} files to knowledge base")

    # 5. Query with agent
    agent = Agent(
        name="Assistant",
        knowledge=knowledge,
        search_knowledge=True,
    )
    response = agent.run("What information is available in the knowledge base?")
    print(f"\nAgent response: {response.content}")


# Run the complete workflow
if __name__ == "__main__":
    asyncio.run(complete_workflow())
