"""
Content Sources for Knowledge — DX Design
============================================================

This cookbook demonstrates the API for adding content from various
remote sources (S3, GCS, SharePoint, GitHub, etc.) to Knowledge.

Key Concepts:
- RemoteContentConfig: Base class for configuring remote content sources
- Each source type has its own config: S3Config, GcsConfig, SharePointConfig, GitHubConfig
- Configs are registered on Knowledge via `content_sources` parameter
- Configs have factory methods (.file(), .folder()) to create content references
- Content references are passed to knowledge.insert()
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import (
    AzureBlobConfig,
    GitHubConfig,
    SharePointConfig,
)
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# Database connections
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)
vector_db = PgVector(
    table_name="knowledge_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Define content source configs (credentials can come from env vars)

sharepoint = SharePointConfig(
    id="sharepoint",
    name="Product Data",
    tenant_id=getenv("SHAREPOINT_TENANT_ID"),  # or os.getenv("SHAREPOINT_TENANT_ID")
    client_id=getenv("SHAREPOINT_CLIENT_ID"),
    client_secret=getenv("SHAREPOINT_CLIENT_SECRET"),
    hostname=getenv("SHAREPOINT_HOSTNAME"),
    site_id=getenv("SHAREPOINT_SITE_ID"),
)

github_docs = GitHubConfig(
    id="my-repo",
    name="My Repository",
    repo="private/repo",
    token=getenv("GITHUB_TOKEN"),  # Fine-grained PAT with Contents: read
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

# Create Knowledge with content sources
knowledge = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[sharepoint, github_docs, azure_blob],
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

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="cloud_agentos:app", reload=True)


# ============================================================================
# Using the Knowledge API
# ============================================================================
"""
Once AgentOS is running, use the Knowledge API to upload content from remote sources.

## Step 1: Get available content sources

    curl -s http://localhost:7777/v1/knowledge/company-knowledge-base/config | jq

Response:
    {
      "remote_content_sources": [
        {"id": "my-repo", "name": "My Repository", "type": "github"},
        ...
      ]
    }

## Step 2: Upload content

    curl -X POST http://localhost:7777/v1/knowledge/company-knowledge-base/remote-content \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Documentation",
        "config_id": "my-repo",
        "path": "docs/README.md"
      }'
"""
