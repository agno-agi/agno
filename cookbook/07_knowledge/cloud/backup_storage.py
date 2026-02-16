"""
Backup Storage
============================================================

Store a raw copy of every ingested file so you can refresh
(re-embed) content later without needing the original file.

Configure backup_storage_config on Knowledge with any storage
backend. When backup=True, the file bytes are saved alongside
the normal chunking and embedding pipeline.

Backends:
- LocalStorageConfig — local filesystem (dev/testing)
- S3Config           — AWS S3 (production)
- AzureBlobConfig    — Azure Blob Storage
- GcsConfig          — Google Cloud Storage
"""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import S3Config
from agno.knowledge.remote_content.config import LocalStorageConfig
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# ============================================================================
# Database
# ============================================================================

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="backup_storage_contents",
)
vector_db = PgVector(
    table_name="backup_storage_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ============================================================================
# Option A: Local filesystem backup (for development)
# ============================================================================

local_backup = LocalStorageConfig(
    id="local-backup",
    name="Local Backup",
    base_path="/tmp/agno-backup-storage",
)

knowledge_local = Knowledge(
    name="backup-storage-local-demo",
    description="Demo with local backup storage",
    contents_db=contents_db,
    vector_db=vector_db,
    backup_storage_config=local_backup,
)

# ============================================================================
# Option B: S3 backup (for production)
# ============================================================================

s3_backup = S3Config(
    id="s3-backup",
    name="S3 Backup",
    bucket_name=getenv("S3_BACKUP_BUCKET", "knowledge-testing-docs"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
    prefix="backup/",
)

s3_backup2 = S3Config(
    id="s3-backup2",
    name="S3 Backup2",
    bucket_name=getenv("S3_BACKUP_BUCKET", "my-knowledge-backup"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
    prefix="backup/",
)
knowledge_s3 = Knowledge(
    name="backup-storage-s3-demo",
    description="Demo with S3 backup storage",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[s3_backup, s3_backup2],
    backup_storage_config=s3_backup,
)

# ============================================================================
# SDK Usage
# ============================================================================
"""
# Insert a file with backup:
knowledge_local.insert(
    name="Q4 Report",
    path="/path/to/q4-report.pdf",
    backup=True,
)

# backup parameter behavior:
#   backup=None (default) — auto-stores backup if backup_storage_config is set
#   backup=True           — force backup (warns if no backup_storage_config)
#   backup=False          — skip backup even if configured

# Refresh content (re-embed from stored bytes):
knowledge_local.refresh_content("content-id-here")

# Async variant:
# await knowledge_local.arefresh_content("content-id-here")
"""

# ============================================================================
# AgentOS
# ============================================================================

agent_os = AgentOS(knowledge=[knowledge_local, knowledge_s3])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="backup_storage:app", reload=True)


# ============================================================================
# API Usage
# ============================================================================
"""
## Upload a file with backup

    curl -X POST http://localhost:7777/v1/knowledge/backup-storage-local-demo/content \
      -F "file=@report.pdf" \
      -F "name=Q4 Report" \
      -F "backup=true"

## Check content status (includes backup storage metadata)

    curl -s http://localhost:7777/v1/knowledge/backup-storage-local-demo/content | jq

## Refresh content (re-embed from backup)

    curl -X POST http://localhost:7777/v1/knowledge/content/{content_id}/refresh

Re-reads the backup bytes, re-chunks, and updates vector embeddings.
Useful when you change chunking settings or embedding models.
"""
