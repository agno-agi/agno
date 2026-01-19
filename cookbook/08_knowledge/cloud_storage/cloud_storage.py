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

from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import (
    GcsConfig,
    GitHubConfig,
    S3Config,
    SharePointConfig,
)
from agno.vectordb.pgvector import PgVector
from agno.os import AgentOS
# Database connections
contents_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
vector_db = PgVector(
    table_name="knowledge_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Define content source configs (credentials can come from env vars)
s3_docs = S3Config(
    id="s3-docs",
    name="S3 Documents",
    bucket_name="acme-company-docs",
)

gcs_data = GcsConfig(
    id="gcs-data",
    name="GCS Training Data",
    bucket_name="acme-ml-data",
    project="acme-ml",
)

sharepoint = SharePointConfig(
    id="sharepoint",
    name="Product Data",
    tenant_id="tenant_id_1",  # or os.getenv("SHAREPOINT_TENANT_ID")
    client_id="client_id_1",
    client_secret="client_secret_1",
    hostname="hostname_1",
)

github_docs = GitHubConfig(
    id="github-docs",
    name="GitHub Documentation",
    repo="acme-corp/docs",
    token="ghp_xxx",  # or os.getenv("GITHUB_TOKEN")
)

# Create Knowledge with content sources
knowledge = Knowledge(
    name="Company Knowledge Base",
    description="Unified knowledge from multiple sources",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[s3_docs, gcs_data, sharepoint, github_docs],
)

# Insert content using factory methods
# The config knows the bucket/credentials, you just specify the file path
knowledge.insert(remote_content=s3_docs.file("reports/q1-2024.pdf"))

# Insert a folder of files
knowledge.insert(remote_content=gcs_data.folder("training-data/"))

# Insert from SharePoint
knowledge.insert(remote_content=sharepoint.file("Documents/product-spec.docx"))

# Insert from GitHub
knowledge.insert(remote_content=github_docs.file("docs/README.md", branch="main"))

agent_os = AgentOS(
    knowledge=[knowledge],
)
app = agent_os.get_app()

# ============================================================================
# Run AgentOS
# ============================================================================
if __name__ == "__main__":
    # Serves a FastAPI app exposed by AgentOS. Use reload=True for local dev.
    agent_os.serve(app="cloud_storage:app", reload=True)
