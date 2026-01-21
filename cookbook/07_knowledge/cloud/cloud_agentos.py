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
    GitHubConfig,
    SharePointConfig,
)
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# Database connections
contents_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
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
    id="dealer-sync",
    name="Dealer Sync",
    repo="willemcdejongh/dealer-sync",
    token=getenv("GITHUB_TESTING_TOKEN"),  # Fine-grained PAT with Contents: read
    branch="main",
)


# Create Knowledge with content sources
knowledge = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[sharepoint, github_docs],
)

# Insert content using factory methods
# The config knows the bucket/credentials, you just specify the file path

# Insert from SharePoint
knowledge.insert(remote_content=sharepoint.file("/test.pdf"))

# Insert from GitHub
knowledge.insert(remote_content=github_docs.file("main.py", branch="main"))

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
