"""
Backup Storage and Content Refresh
============================================================

Demonstrates how to configure backup storage on Knowledge so that
raw files are preserved alongside their embeddings. This enables
content refresh (re-embedding from the original file or backup)
without needing to re-upload.

Backup storage supports four backends:
- S3Config: Production use on AWS
- GcsConfig: Google Cloud Storage
- AzureBlobConfig: Azure Blob Storage
- LocalStorageConfig: Local filesystem (development/testing)

Run:
    python cookbook/07_knowledge/cloud/backup_storage.py

Key Concepts:
- backup_storage_config on Knowledge sets where raw files are stored
- backup=True on insert() stores the raw file alongside embeddings
- refresh_content() re-fetches and re-embeds content from backup or source
- LocalStorageConfig is ideal for local development and testing
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import LocalStorageConfig, S3Config
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

# --- Backup Storage Config ---
# For local development, use LocalStorageConfig to store raw files on disk.
# For production, use S3Config, GcsConfig, or AzureBlobConfig.
if getenv("BACKUP_S3_BUCKET"):
    backup_config = S3Config(
        id="backup-s3",
        name="Backup Storage",
        bucket_name=getenv("BACKUP_S3_BUCKET", ""),
        region=getenv("AWS_REGION", "us-east-1"),
        aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
        prefix="backups/",
    )
else:
    backup_config = LocalStorageConfig(
        id="backup-local",
        name="Local Backup",
        base_path="/tmp/agno-backups",
    )

# Create Knowledge with backup storage enabled
knowledge = Knowledge(
    name="Knowledge with Backup",
    description="Knowledge base with backup storage for content refresh",
    contents_db=contents_db,
    vector_db=vector_db,
    backup_storage_config=backup_config,
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
    agent_os.serve(app="backup_storage:app", reload=True)


# ============================================================================
# Usage
# ============================================================================
"""
## Insert content with backup

When backup_storage_config is set, inserts automatically back up raw files.
You can also explicitly control this with the backup parameter:

    # Via API
    curl -X POST http://localhost:7777/v1/knowledge/knowledge-with-backup/content \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Report",
        "url": "https://example.com/report.pdf"
      }'

    # Via Python
    knowledge.insert(
        name="Report",
        url="https://example.com/report.pdf",
        backup=True,   # explicit; None=auto (backs up if config is set)
    )

## Refresh content

Re-fetch from the original source or backup and re-embed:

    # Via API
    curl -X POST http://localhost:7777/v1/knowledge/knowledge-with-backup/content/<content_id>/refresh

    # Via Python
    knowledge.refresh_content(content_id="<content_id>")

Refresh priority:
1. Original source (URL, S3, etc.) if still accessible
2. Backup storage as fallback
"""
