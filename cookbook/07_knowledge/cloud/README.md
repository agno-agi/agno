# Cloud Storage Knowledge Cookbooks

This folder contains cookbooks demonstrating how to work with cloud storage sources in Agno Knowledge.

## Prerequisites

```bash
# Start PostgreSQL with pgvector
./cookbook/scripts/run_pgvector.sh

# Activate demo environment
source .venvs/demo/bin/activate
```

## Cookbooks

### `s3_sources.py` — S3 File Browsing API

Demonstrates the new S3 file browsing API that lets you list and navigate S3 bucket contents before ingesting.

```bash
# Start the server
.venvs/demo/bin/python cookbook/07_knowledge/cloud/s3_sources.py

# List sources
curl -s http://localhost:7777/v1/knowledge/sources | jq

# Browse files
curl -s "http://localhost:7777/v1/knowledge/sources/company-docs/files" | jq

# Navigate folders
curl -s "http://localhost:7777/v1/knowledge/sources/company-docs/files?prefix=reports/" | jq
```

### `s3_direct.py` — Direct S3 Listing (No Server)

Use `S3Config.list_files()` directly in scripts without running AgentOS.

```bash
export S3_BUCKET_NAME=my-bucket
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
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

### `cloud_agentos.py` — Multi-Source Knowledge Base

Full example with SharePoint, GitHub, and Azure Blob sources.

```bash
.venvs/demo/bin/python cookbook/07_knowledge/cloud/cloud_agentos.py
```

### Provider-Specific Examples

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
GET /v1/knowledge/sources
```

Returns all configured content sources.

### List Files
```
GET /v1/knowledge/sources/{source_id}/files
```

Query parameters:
- `prefix` — Path prefix to filter (e.g., `reports/2024/`)
- `limit` — Files per page (1-1000, default 100)
- `page` — Page number (1-indexed, default 1)
- `delimiter` — Folder delimiter (default `/`)

Response includes `meta` with pagination info:
```json
{
  "files": [...],
  "folders": [...],
  "meta": {"page": 1, "limit": 100, "total_pages": 5, "total_count": 450}
}
```

### Upload Content
```
POST /v1/knowledge/{knowledge_id}/remote-content
```

Body:
```json
{
  "name": "My Document",
  "config_id": "source-id",
  "path": "folder/file.pdf"
}
```
