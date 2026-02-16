"""
Backup and Refresh — Advanced Patterns
============================================================

Shows what happens when a remote content source is also configured
as the backup storage location, and how content refresh works.

Key behaviors:
1. A backup copy is ALWAYS created — even when the source and backup
   storage point to the same location. This ensures the backup is
   under a known, stable key that won't change if the original file
   is moved or deleted.

2. On refresh, the original source is tried first. If the original
   source fails (file moved, deleted, credentials expired), the
   backup copy is used as a fallback.

This pattern is useful in production where your documents live in S3
and you want the same bucket to serve as backup storage.
"""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import S3Config
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# ============================================================================
# Database
# ============================================================================

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="advanced_backup_contents",
)
vector_db = PgVector(
    table_name="advanced_backup_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ============================================================================
# Same S3 bucket as both content source and backup storage
# ============================================================================
# The content source is where your documents live (e.g. "documents/" prefix).
# The backup storage uses a separate prefix (e.g. "backup/") in the same bucket.

s3_docs = S3Config(
    id="s3-docs",
    name="Company Documents",
    bucket_name=getenv("S3_BUCKET_NAME", "my-company-bucket"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
    prefix="documents/",
)

s3_backup = S3Config(
    id="s3-backup",
    name="Backup Storage",
    bucket_name=getenv("S3_BUCKET_NAME", "my-company-bucket"),  # Same bucket
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
    prefix="backup/",  # Different prefix
)

knowledge = Knowledge(
    name="advanced-backup-demo",
    description="Same bucket for content and backup",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[s3_docs],
    backup_storage_config=s3_backup,
)

# ============================================================================
# SDK Usage
# ============================================================================
"""
# 1. Ingest from S3 with backup enabled
#    - File is read from s3://my-company-bucket/documents/report.pdf
#    - Backup copy stored at s3://my-company-bucket/backup/<content-id>/report.pdf
#    - Content is chunked and embedded as normal
knowledge.insert(
    name="Q4 Report",
    remote_content=s3_docs.file("report.pdf"),
    backup=True,
)

# 2. Refresh — re-embed with new settings
#    Priority order:
#      a) Try original source: s3://my-company-bucket/documents/report.pdf
#      b) If that fails, fall back to backup: s3://my-company-bucket/backup/<id>/report.pdf
#
#    This means if someone moves the original file, refresh still works
#    because the backup copy is stored under a stable, content-id-based key.
knowledge.refresh_content("content-id-here")
"""

# ============================================================================
# AgentOS
# ============================================================================

agent_os = AgentOS(knowledge=[knowledge])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="backup_and_refresh:app", reload=True)


# ============================================================================
# API Usage
# ============================================================================
"""
## Ingest a file from the S3 content source with backup

    curl -X POST http://localhost:7777/v1/knowledge/advanced-backup-demo/remote-content \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Q4 Report",
        "config_id": "s3-docs",
        "path": "report.pdf",
        "backup": true
      }'

## Check status (shows both source_type and backup_storage_type in _agno metadata)

    curl -s http://localhost:7777/v1/knowledge/content/{content_id}/status | jq

    Response when ready:
    {
      "id": "...",
      "status": "completed",
      "status_message": "refresh_available"
    }

## Refresh content

    curl -X POST http://localhost:7777/v1/knowledge/content/{content_id}/refresh

    Tries the original S3 source first. If the file was moved or deleted,
    falls back to the backup copy automatically.
"""
