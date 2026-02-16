# Cloud Storage Knowledge Cookbooks

This folder contains cookbooks demonstrating how to work with cloud storage sources in Agno Knowledge.

## Prerequisites

```bash
# Start PostgreSQL with pgvector
./cookbook/scripts/run_pgvector.sh

# Activate demo environment
source .venvs/demo/bin/activate
```

## Core Cookbooks

### `remote_content.py` — Remote Content Sources

Configure cloud storage providers and ingest content from them. Supports S3, GCS, SharePoint, GitHub, and Azure Blob.

```bash
.venvs/demo/bin/python cookbook/07_knowledge/cloud/remote_content.py
```

```python
knowledge = Knowledge(
    content_sources=[s3_docs, github_docs, azure_blob],
    ...
)
knowledge.insert(
    name="Q4 Report",
    remote_content=s3_docs.file("reports/q4-report.pdf"),
)
```

### `backup_storage.py` — Backup Storage

Store a raw copy of ingested files for later refresh (re-embedding). Shows local filesystem (dev) and S3 (production) backends.

```bash
.venvs/demo/bin/python cookbook/07_knowledge/cloud/backup_storage.py
```

```python
knowledge = Knowledge(
    backup_storage_config=local_backup,
    ...
)
knowledge.insert(name="Report", path="report.pdf", backup=True)
knowledge.refresh_content("content-id")
```

### `backup_and_refresh.py` — Advanced: Combined Source + Backup

Shows what happens when the same S3 bucket is used for both content source and backup storage. Backup copies are always created. On refresh, the original source is tried first with backup as fallback.

```bash
.venvs/demo/bin/python cookbook/07_knowledge/cloud/backup_and_refresh.py
```

## S3 File Browsing

### `s3_sources.py` — S3 File Browsing API

List and navigate S3 bucket contents before ingesting via the AgentOS API.

```bash
.venvs/demo/bin/python cookbook/07_knowledge/cloud/s3_sources.py

curl -s "http://localhost:7777/v1/knowledge/s3-sources-demo/sources/company-docs/files" | jq
```

### `s3_direct.py` — Direct S3 Listing (No Server)

Use `S3Config.list_files()` directly in scripts without running AgentOS.

```bash
.venvs/demo/bin/python cookbook/07_knowledge/cloud/s3_direct.py
```

### `test_s3_api.py` — API Test Suite

Automated tests for the S3 browsing API endpoints.

```bash
# Terminal 1: Start server
.venvs/demo/bin/python cookbook/07_knowledge/cloud/s3_sources.py

# Terminal 2: Run tests
.venvs/demo/bin/python cookbook/07_knowledge/cloud/test_s3_api.py
```

## Provider-Specific Examples

- `azure_blob.py` — Azure Blob Storage integration
- `github.py` — GitHub repository content
- `sharepoint.py` — Microsoft SharePoint documents

## Environment Variables

### S3/AWS
```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1
export S3_BUCKET_NAME=my-bucket
```

### Azure Blob
```bash
export AZURE_TENANT_ID=...
export AZURE_CLIENT_ID=...
export AZURE_CLIENT_SECRET=...
export AZURE_STORAGE_ACCOUNT_NAME=...
export AZURE_CONTAINER_NAME=...
```

### SharePoint
```bash
export SHAREPOINT_TENANT_ID=...
export SHAREPOINT_CLIENT_ID=...
export SHAREPOINT_CLIENT_SECRET=...
export SHAREPOINT_HOSTNAME=contoso.sharepoint.com
export SHAREPOINT_SITE_ID=...
```

### GitHub
```bash
export GITHUB_TOKEN=ghp_...  # Fine-grained PAT with Contents: read
```

## API Reference

### List Sources
```
GET /v1/knowledge/{knowledge_id}/sources
```

Returns all configured content sources for a knowledge base.

### List Files (S3 only)
```
GET /v1/knowledge/{knowledge_id}/sources/{source_id}/files
```

Query parameters:
- `prefix` — Path prefix to filter (e.g., `reports/2024/`)
- `limit` — Files per page (1-1000, default 100)
- `page` — Page number (1-indexed, default 1)
- `delimiter` — Folder delimiter (default `/`)

### Upload Content
```
POST /v1/knowledge/{knowledge_id}/content
```

Form fields:
- `file` — File to upload
- `name` — Content name
- `backup` — (optional) `true` to store file bytes for later refresh

```
POST /v1/knowledge/{knowledge_id}/remote-content
```

Body:
```json
{
  "name": "My Document",
  "config_id": "source-id",
  "path": "folder/file.pdf",
  "backup": true
}
```

### Refresh Content
```
POST /v1/knowledge/content/{content_id}/refresh
```

Tries the original cloud source first, falls back to backup storage. Returns 202 on success, 404 if content not found, 422 if no source available.
