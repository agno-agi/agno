"""
Remote Content Sources
============================================================

Ingest content from cloud storage providers into your Knowledge base.

Each provider has a Config class with .file() and .folder() methods
that create content references. Pass these to knowledge.insert().

Supported providers:
- S3Config       — AWS S3
- GcsConfig      — Google Cloud Storage
- AzureBlobConfig — Azure Blob Storage
- SharePointConfig — Microsoft SharePoint
- GitHubConfig   — GitHub repositories
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import (
    AzureBlobConfig,
    GitHubConfig,
    S3Config,
    SharePointConfig,
)
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# ============================================================================
# Database
# ============================================================================

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="remote_content_contents",
)
vector_db = PgVector(
    table_name="remote_content_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ============================================================================
# Configure content sources
# ============================================================================

s3_docs = S3Config(
    id="s3-docs",
    name="S3 Documents",
    bucket_name=getenv("S3_BUCKET_NAME", "my-company-docs"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
)

sharepoint = SharePointConfig(
    id="sharepoint",
    name="Product Data",
    tenant_id=getenv("SHAREPOINT_TENANT_ID"),
    client_id=getenv("SHAREPOINT_CLIENT_ID"),
    client_secret=getenv("SHAREPOINT_CLIENT_SECRET"),
    hostname=getenv("SHAREPOINT_HOSTNAME"),
    site_id=getenv("SHAREPOINT_SITE_ID"),
)

github_docs = GitHubConfig(
    id="my-repo",
    name="My Repository",
    repo="owner/repo",
    token=getenv("GITHUB_TOKEN"),
    branch="main",
)

azure_blob = AzureBlobConfig(
    id="azure-blob",
    name="Azure Blob",
    tenant_id=getenv("AZURE_TENANT_ID"),
    client_id=getenv("AZURE_CLIENT_ID"),
    client_secret=getenv("AZURE_CLIENT_SECRET"),
    storage_account=getenv("AZURE_STORAGE_ACCOUNT_NAME"),
    container=getenv("AZURE_CONTAINER_NAME"),
)

# ============================================================================
# Create Knowledge with content sources
# ============================================================================

knowledge = Knowledge(
    name="remote-content-demo",
    description="Knowledge base with multiple remote content sources",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[s3_docs, sharepoint, github_docs, azure_blob],
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    knowledge=knowledge,
    search_knowledge=True,
)

agent_os = AgentOS(
    knowledge=[knowledge],
    agents=[agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="remote_content:app", reload=True)


# ============================================================================
# SDK Usage
# ============================================================================
"""
# Insert a single file from S3:
knowledge.insert(
    name="Q4 Report",
    remote_content=s3_docs.file("reports/q4-report.pdf"),
)

# Insert an entire folder from GitHub:
knowledge.insert(
    name="Documentation",
    remote_content=github_docs.folder("docs/"),
)

# Insert from SharePoint:
knowledge.insert(
    name="Policies",
    remote_content=sharepoint.folder("Shared Documents/Policies"),
)

# Insert from Azure Blob:
knowledge.insert(
    name="Research Paper",
    remote_content=azure_blob.file("papers/deepseek.pdf"),
)
"""


# ============================================================================
# API Usage
# ============================================================================
"""
## List configured sources

    curl -s http://localhost:7777/v1/knowledge/remote-content-demo/config | jq

## Browse S3 files (S3 sources only)

    curl -s "http://localhost:7777/v1/knowledge/remote-content-demo/sources/s3-docs/files" | jq

## Ingest from a remote source

    curl -X POST http://localhost:7777/v1/knowledge/remote-content-demo/remote-content \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Q4 Report",
        "config_id": "s3-docs",
        "path": "reports/q4-report.pdf"
      }'
"""
