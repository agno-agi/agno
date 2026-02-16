"""
S3 Content Sources — List and Browse Files
============================================================

This cookbook demonstrates the new S3 file browsing API that allows
you to list files and folders in S3 buckets before ingesting them.

Key Features:
- List all configured content sources
- Browse S3 bucket contents with pagination
- Navigate folders hierarchically
- View file metadata (size, last modified, etc.)

Requirements:
- boto3: pip install boto3
- AWS credentials configured (env vars or IAM role)
"""

from os import getenv

from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content import S3Config
from agno.os import AgentOS
from agno.vectordb.pgvector import PgVector

# Database connections
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="s3_sources_contents",
)
vector_db = PgVector(
    table_name="s3_sources_vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Configure S3 source
# Credentials from environment or IAM role
s3_docs = S3Config(
    id="company-docs",
    name="Company Documents",
    bucket_name=getenv("S3_BUCKET_NAME", "my-company-docs"),
    region=getenv("AWS_REGION", "us-east-1"),
    aws_access_key_id=getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=getenv("AWS_SECRET_ACCESS_KEY"),
    prefix="documents/",  # Optional: default prefix for browsing
)

# Create Knowledge with S3 source
knowledge = Knowledge(
    name="s3-sources-demo",
    description="Demo of S3 source browsing",
    contents_db=contents_db,
    vector_db=vector_db,
    content_sources=[s3_docs],
)

# Create AgentOS to serve the API
agent_os = AgentOS(knowledge=[knowledge])
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="s3_sources:app", reload=True)


# ============================================================================
# API Usage Examples
# ============================================================================
"""
Once the server is running, use these endpoints to browse S3 content:

## 1. List all configured sources

    curl -s http://localhost:7777/v1/knowledge/s3-sources-demo/sources | jq

Response:
    [
      {
        "id": "company-docs",
        "name": "Company Documents",
        "type": "s3",
        "prefix": "documents/"
      }
    ]


## 2. List files at the root of a source

    curl -s "http://localhost:7777/v1/knowledge/s3-sources-demo/sources/company-docs/files" | jq

Response:
    {
      "source_id": "company-docs",
      "source_name": "Company Documents",
      "prefix": "",
      "folders": [
        {"prefix": "reports/", "name": "reports", "is_empty": false},
        {"prefix": "policies/", "name": "policies", "is_empty": false}
      ],
      "files": [
        {
          "key": "readme.txt",
          "name": "readme.txt",
          "size": 1024,
          "last_modified": "2024-01-15T10:30:00Z",
          "content_type": null
        }
      ],
      "meta": {"page": 1, "limit": 100, "total_pages": 1, "total_count": 1}
    }


## 3. Navigate into a folder

    curl -s "http://localhost:7777/v1/knowledge/s3-sources-demo/sources/company-docs/files?prefix=reports/" | jq


## 4. Paginate through large folders

    # First page
    curl -s "http://localhost:7777/v1/knowledge/s3-sources-demo/sources/company-docs/files?limit=10" | jq

    # Page 2
    curl -s "http://localhost:7777/v1/knowledge/s3-sources-demo/sources/company-docs/files?limit=10&page=2" | jq


## 5. After browsing, ingest specific files

    curl -X POST http://localhost:7777/v1/knowledge/s3-sources-demo/remote-content \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "Q4 Report",
        "config_id": "company-docs",
        "path": "reports/2024/q4-summary.pdf"
      }'
"""
