"""
Raw Content Storage & Content Refresh
============================================================

This cookbook demonstrates how to store raw file contents during ingestion
and refresh (re-embed) content later without needing the original file.

Key Concepts:
- raw_storage_config: Config object (S3Config or LocalStorageConfig) for raw file storage
- store_raw: Parameter on insert() and API to trigger raw storage
- LocalStorageConfig: Dev-friendly storage to local filesystem (no cloud needed)
- S3Config: Production raw storage to S3
- Content refresh: Re-fetch raw bytes and re-embed with current settings

Two examples:
1. SDK usage with knowledge.insert(store_raw=True)
2. AgentOS API usage with the store_raw form field and refresh endpoint
"""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import S3Config
from agno.knowledge.remote_content.config import LocalStorageConfig
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# ============================================================================
# Database connections
# ============================================================================

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="raw_storage_contents",
)
vector_db = PgVector(
    table_name="raw_storage_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# ============================================================================
# Option A: Local raw storage (for development/testing)
# ============================================================================

local_storage = LocalStorageConfig(
    id="local-raw",
    name="Local Raw Storage",
    base_path="/tmp/agno-raw-storage",
)

knowledge_local = Knowledge(
    name="raw-storage-local-demo",
    description="Demo with local raw storage",
    contents_db=contents_db,
    vector_db=vector_db,
    raw_storage_config=local_storage,  # Pass the config object directly
)

# ============================================================================
# Option B: S3 raw storage (for production)
# ============================================================================

s3_raw = S3Config(
    id="s3-raw",
    name="S3 Raw Storage",
    bucket_name=getenv("S3_RAW_BUCKET", "my-knowledge-raw"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
    prefix="raw/",  # All raw files stored under raw/ prefix
)

# You can also have a separate source config for ingesting content
s3_docs = S3Config(
    id="s3-docs",
    name="Company Documents",
    bucket_name=getenv("S3_BUCKET_NAME", "my-company-docs"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
)

knowledge_s3 = Knowledge(
    name="raw-storage-s3-demo",
    description="Demo with S3 raw storage",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[s3_docs],  # Document source for ingestion
    raw_storage_config=s3_raw,  # Separate config for raw storage (not in content_sources)
)

# ============================================================================
# SDK Usage: insert with store_raw
# ============================================================================
"""
# Insert a local file and store raw copy:
knowledge_local.insert(
    name="Q4 Report",
    path="/path/to/q4-report.pdf",
    store_raw=True,  # Force store raw copy to local filesystem
)

# Insert from S3 source and store raw copy:
knowledge_s3.insert(
    name="Engineering Spec",
    remote_content=s3_docs.file("specs/engineering-spec.pdf"),
    store_raw=True,  # Store raw copy to s3-raw bucket
)

# store_raw behavior:
# - store_raw=None (default): auto-stores if raw_storage_config is set
# - store_raw=True: force store (warns if no raw_storage_config)
# - store_raw=False: skip raw storage even if configured

# Refresh content (re-embed from stored raw bytes):
knowledge_local.refresh_content("content-id-here")

# Async variant:
# await knowledge_local.arefresh_content("content-id-here")
"""

# ============================================================================
# AgentOS: Serve with raw storage enabled
# ============================================================================

# Use the local storage version for this demo
agent_os = AgentOS(knowledge=[knowledge_local])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="raw_storage:app", reload=True)


# ============================================================================
# API Usage Examples
# ============================================================================
"""
Once the server is running, use these endpoints:

## 1. Upload a file with raw storage

    curl -X POST http://localhost:7777/v1/knowledge/raw-storage-local-demo/content \
      -F "file=@report.pdf" \
      -F "name=Q4 Report" \
      -F "store_raw=true"

The raw file bytes are stored to the configured backend (local filesystem
in this case) and the content is chunked and embedded as normal.


## 2. Upload remote content with raw storage

    curl -X POST http://localhost:7777/v1/knowledge/raw-storage-local-demo/remote-content \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Engineering Spec",
        "config_id": "s3-docs",
        "path": "specs/engineering-spec.pdf",
        "store_raw": true
      }'


## 3. Refresh content (re-embed from raw storage)

    curl -X POST http://localhost:7777/v1/knowledge/content/{content_id}/refresh

This fetches the raw bytes from storage, re-reads and re-chunks the
content, and updates the vector embeddings. Useful when you change
chunking settings or embedding models.


## 4. Check content metadata (see raw storage info)

    curl -s http://localhost:7777/v1/knowledge/raw-storage-local-demo/content | jq

Response includes _agno metadata with raw storage info:
    {
      "metadata": {
        "_agno": {
          "raw_storage_type": "local",
          "raw_storage_path": "/tmp/agno-raw-storage/<content_id>/report.pdf",
          "raw_storage_config_id": "local-raw"
        }
      }
    }
"""
