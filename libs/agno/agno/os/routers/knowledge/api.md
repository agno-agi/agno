# Knowledge Content Sources API

API endpoints for managing content sources (S3, GCS, SharePoint, GitHub) on Knowledge.

---

## Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/knowledge/sources` | GET | List all registered content sources |
| `/knowledge/sources/{source_id}/files` | GET | List files in a specific source |
| `/knowledge/content/from-source` | POST | Add single file from a source |
| `/knowledge/content/from-source/batch` | POST | Add multiple files from a source |

---

## 1. List Content Sources

**GET** `/knowledge/sources`

Returns all registered content sources for the knowledge base.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `db_id` | string | No | Database ID to use |

### Response `200 OK`

```json
[
  {
    "id": "company-s3",
    "name": "Company Documents",
    "description": "S3 bucket with company docs",
    "type": "s3",
    "prefix": "documents/"
  },
  {
    "id": "eng-sharepoint",
    "name": "Engineering SharePoint",
    "description": null,
    "type": "sharepoint",
    "prefix": null
  },
  {
    "id": "internal-github",
    "name": "Internal Documentation",
    "description": "Private GitHub repo",
    "type": "github",
    "prefix": "docs/"
  }
]
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier for the source |
| `name` | string | Human-readable name |
| `description` | string \| null | Optional description |
| `type` | string | Source type: `s3`, `gcs`, `sharepoint`, `github` |
| `prefix` | string \| null | Default path prefix for this source |

---

## 2. List Files in Source

**GET** `/knowledge/sources/{source_id}/files`

Lists available files and folders in a specific content source. Supports cursor-based pagination and folder navigation.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `source_id` | string | Yes | ID of the content source |

### Query Parameters

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `prefix` | string | `""` | No | Path prefix to filter files (e.g., `reports/2024/`) |
| `limit` | integer | `100` | No | Max files to return per request (1-1000) |
| `cursor` | string | null | No | Continuation token from previous response |
| `delimiter` | string | `"/"` | No | Folder delimiter (enables folder grouping) |
| `db_id` | string | null | No | Database ID to use |

### Response `200 OK`

```json
{
  "source_id": "company-s3",
  "source_name": "Company Documents",
  "prefix": "reports/",
  "folders": [
    {
      "prefix": "reports/2023/",
      "name": "2023"
    },
    {
      "prefix": "reports/2024/",
      "name": "2024"
    }
  ],
  "files": [
    {
      "key": "reports/annual-summary.pdf",
      "name": "annual-summary.pdf",
      "size": 102400,
      "last_modified": "2024-01-15T10:30:00Z",
      "content_type": "application/pdf"
    },
    {
      "key": "reports/quarterly-template.docx",
      "name": "quarterly-template.docx",
      "size": 45056,
      "last_modified": "2024-02-20T09:15:00Z",
      "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
  ],
  "file_count": 2,
  "has_more": true,
  "next_cursor": "eyJrZXkiOiJyZXBvcnRzL3F1YXJ0ZXJseS10ZW1wbGF0ZS5kb2N4In0="
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `source_id` | string | ID of the content source |
| `source_name` | string | Name of the content source |
| `prefix` | string \| null | Prefix filter that was applied |
| `folders` | array | Subfolders at this level (when delimiter is used) |
| `folders[].prefix` | string | Full prefix to use for navigating into this folder |
| `folders[].name` | string | Display name of the folder |
| `files` | array | List of files at this level |
| `files[].key` | string | Full path/key of the file |
| `files[].name` | string | Display name (filename) |
| `files[].size` | integer \| null | File size in bytes |
| `files[].last_modified` | string \| null | ISO 8601 timestamp |
| `files[].content_type` | string \| null | MIME type |
| `file_count` | integer | Number of files in this response |
| `has_more` | boolean | Whether more files exist (for pagination) |
| `next_cursor` | string \| null | Token for fetching next page of files |

### Pagination

Use cursor-based pagination to handle large directories:

1. First request: `GET /knowledge/sources/s3/files?prefix=reports/&limit=50`
2. If `has_more` is `true`, fetch next page: `GET /knowledge/sources/s3/files?prefix=reports/&limit=50&cursor={next_cursor}`
3. Repeat until `has_more` is `false`

### Folder Navigation

When `delimiter` is set (default `/`), the response groups objects by folder:

- `folders[]` contains immediate subfolders at the current prefix level
- `files[]` contains only files directly at this level (not in subfolders)
- To navigate into a folder, use its `prefix` value in the next request

### Errors

| Status | Description |
|--------|-------------|
| `404` | Content source not found |
| `400` | Invalid cursor token |

---

## 3. Add Content from Source

**POST** `/knowledge/content/from-source`

Add a single file from a content source to the knowledge base.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `db_id` | string | No | Database ID to use |

### Request Body

```json
{
  "source_id": "company-s3",
  "key": "reports/2024/q1-report.pdf",
  "name": "Q1 2024 Financial Report",
  "description": "Quarterly financial report for Q1 2024",
  "metadata": {
    "department": "finance",
    "year": "2024",
    "quarter": "Q1"
  },
  "reader_id": "pdf",
  "chunker": "RecursiveChunker",
  "chunk_size": 1000,
  "chunk_overlap": 200
}
```

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_id` | string | Yes | ID of the content source |
| `key` | string | Yes | File key/path within the source |
| `name` | string | No | Display name (defaults to filename) |
| `description` | string | No | Content description |
| `metadata` | object | No | Additional metadata |
| `reader_id` | string | No | Reader to use for processing |
| `chunker` | string | No | Chunking strategy |
| `chunk_size` | integer | No | Chunk size |
| `chunk_overlap` | integer | No | Chunk overlap |

### Response `202 Accepted`

```json
{
  "id": "content-abc123def456",
  "name": "Q1 2024 Financial Report",
  "description": "Quarterly financial report for Q1 2024",
  "metadata": {
    "department": "finance",
    "year": "2024",
    "quarter": "Q1",
    "_source_id": "company-s3",
    "_source_key": "reports/2024/q1-report.pdf"
  },
  "status": "processing"
}
```

### Errors

| Status | Description |
|--------|-------------|
| `404` | Content source not found |
| `400` | Invalid file key or source configuration error |

---

## 4. Add Multiple Files from Source (Batch)

**POST** `/knowledge/content/from-source/batch`

Add multiple files from a content source in a single request.

### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `db_id` | string | No | Database ID to use |

### Request Body

```json
{
  "source_id": "company-s3",
  "keys": [
    "reports/2024/q1-report.pdf",
    "reports/2024/q2-report.pdf",
    "policies/security-policy.pdf"
  ],
  "metadata": {
    "batch_import": "true",
    "imported_by": "admin"
  },
  "reader_id": "pdf",
  "chunker": "RecursiveChunker"
}
```

### Request Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `source_id` | string | Yes | ID of the content source |
| `keys` | array[string] | Yes | List of file keys to add (min 1) |
| `metadata` | object | No | Metadata applied to all files |
| `reader_id` | string | No | Reader to use for processing |
| `chunker` | string | No | Chunking strategy |
| `chunk_size` | integer | No | Chunk size |
| `chunk_overlap` | integer | No | Chunk overlap |

### Response `202 Accepted`

```json
{
  "accepted": 3,
  "content_ids": [
    "content-abc123",
    "content-def456",
    "content-ghi789"
  ],
  "source_id": "company-s3"
}
```

### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `accepted` | integer | Number of files accepted for processing |
| `content_ids` | array[string] | List of content IDs created |
| `source_id` | string | Source ID files were added from |

### Errors

| Status | Description |
|--------|-------------|
| `404` | Content source not found |

---

## UI Workflow Example

### Basic Flow with Folder Navigation

```
1. Page Load
   ↓
   GET /knowledge/sources
   → Display source dropdown

2. User Selects Source "company-s3"
   ↓
   GET /knowledge/sources/company-s3/files?delimiter=/
   → Display root folders and files
   → Response: { folders: [{prefix: "reports/", name: "reports"}, ...], files: [...] }

3. User Clicks "reports/" Folder
   ↓
   GET /knowledge/sources/company-s3/files?prefix=reports/&delimiter=/
   → Display subfolders (2023/, 2024/) and files in reports/
   → Response: { folders: [{prefix: "reports/2024/", name: "2024"}], files: [...] }

4. User Clicks "2024/" Folder
   ↓
   GET /knowledge/sources/company-s3/files?prefix=reports/2024/&delimiter=/
   → Display files in reports/2024/
   → Response: { folders: [], files: [...], has_more: false }

5. User Selects 3 Files and Clicks "Add"
   ↓
   POST /knowledge/content/from-source/batch
   {
     "source_id": "company-s3",
     "keys": ["reports/2024/q1.pdf", "reports/2024/q2.pdf", "reports/2024/q3.pdf"]
   }
   → Show "3 files queued for processing"

6. Poll for Status (existing endpoint)
   ↓
   GET /knowledge/content/{content_id}/status
   → Update progress UI
```

### Pagination Flow (Large Directories)

```
1. Initial Load of Large Folder
   ↓
   GET /knowledge/sources/company-s3/files?prefix=logs/&limit=100
   → Response: { files: [...100 files...], has_more: true, next_cursor: "abc123" }
   → Display first 100 files with "Load More" button

2. User Clicks "Load More"
   ↓
   GET /knowledge/sources/company-s3/files?prefix=logs/&limit=100&cursor=abc123
   → Response: { files: [...next 100 files...], has_more: true, next_cursor: "def456" }
   → Append files to list

3. User Clicks "Load More" Again
   ↓
   GET /knowledge/sources/company-s3/files?prefix=logs/&limit=100&cursor=def456
   → Response: { files: [...final 50 files...], has_more: false, next_cursor: null }
   → Append files, hide "Load More" button
```

---

## Content Source Types

| Type | Description | Key Format |
|------|-------------|------------|
| `s3` | AWS S3 bucket | `path/to/file.pdf` |
| `gcs` | Google Cloud Storage | `path/to/file.pdf` |
| `sharepoint` | Microsoft SharePoint | `Library/Folder/file.docx` |
| `github` | GitHub repository | `path/to/file.md` |
