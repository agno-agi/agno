# Knowledge Content Sources API

API endpoints for managing content sources (S3, GCS, SharePoint, GitHub) on Knowledge.

---

## Endpoints Summary

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/knowledge/{knowledge_id}/sources` | GET | List all registered content sources |
| `/knowledge/{knowledge_id}/sources/{source_id}/files` | GET | List files in a specific source |
| `/knowledge/{knowledge_id}/content/from-source` | POST | Add single file from a source |
| `/knowledge/{knowledge_id}/content/from-source/batch` | POST | Add multiple files from a source |

---

## 1. List Content Sources

**GET** `/knowledge/{knowledge_id}/sources`

Returns all registered content sources for the knowledge base.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `knowledge_id` | string | Yes | ID of the knowledge base |

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

### Errors

| Status | Description |
|--------|-------------|
| `404` | Knowledge base not found |

---

## 2. List Files in Source

**GET** `/knowledge/{knowledge_id}/sources/{source_id}/files`

Lists available files and folders in a specific content source. Supports cursor-based pagination and folder navigation.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `knowledge_id` | string | Yes | ID of the knowledge base |
| `source_id` | string | Yes | ID of the content source |

### Query Parameters

| Parameter | Type | Default | Required | Description |
|-----------|------|---------|----------|-------------|
| `prefix` | string | `""` | No | Path prefix to filter files (e.g., `reports/2024/`) |
| `limit` | integer | `100` | No | Max files to return per request (1-1000) |
| `cursor` | string | null | No | Opaque continuation token from previous response |
| `delimiter` | string | `"/"` | No | Folder delimiter (enables folder grouping) |

### Response `200 OK`

```json
{
  "source_id": "company-s3",
  "source_name": "Company Documents",
  "prefix": "reports/",
  "folders": [
    {
      "prefix": "reports/2023/",
      "name": "2023",
      "is_empty": false
    },
    {
      "prefix": "reports/2024/",
      "name": "2024",
      "is_empty": false
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
  "next_cursor": "1AfterKeyXYZ..."
  {}
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
| `folders[].is_empty` | boolean | Whether the folder contains any files (cheap check) |
| `files` | array | List of files at this level |
| `files[].key` | string | Full path/key of the file |
| `files[].name` | string | Display name (filename) |
| `files[].size` | integer \| null | File size in bytes |
| `files[].last_modified` | string \| null | ISO 8601 timestamp |
| `files[].content_type` | string \| null | MIME type |
| `file_count` | integer | Number of files in this response |
| `next_cursor` | string \| null | Opaque token for next page. `null` if no more results. |

### Pagination

Use cursor-based pagination to handle large directories:

1. First request: `GET /knowledge/{knowledge_id}/sources/{source_id}/files?prefix=reports/&limit=50`
2. If `next_cursor` is not `null`, fetch next page: `GET /knowledge/{knowledge_id}/sources/{source_id}/files?prefix=reports/&limit=50&cursor={next_cursor}`
3. Repeat until `next_cursor` is `null`

**Cursor behavior:**
- Cursors are **opaque** — clients must not parse, modify, or construct them
- Simply pass the `next_cursor` value back as the `cursor` parameter
- When `next_cursor` is `null`, there are no more results

### Folder Navigation

When `delimiter` is set (default `/`), the response groups objects by folder:

- `folders[]` contains immediate subfolders at the current prefix level
- `files[]` contains only files directly at this level (not in subfolders)
- To navigate into a folder, use its `prefix` value in the next request
- `is_empty` indicates whether a folder has any content (useful for UI indicators)

### Sample Responses: Folder Navigation Flow

**Step 1: Request root level**

```
GET /knowledge/kb-main/sources/company-s3/files
```

```json
{
  "source_id": "company-s3",
  "source_name": "Company Documents",
  "prefix": "",
  "folders": [
    { "prefix": "docs/", "name": "docs", "is_empty": false },
    { "prefix": "reports/", "name": "reports", "is_empty": false },
    { "prefix": "templates/", "name": "templates", "is_empty": true }
  ],
  "files": [
    {
      "key": "README.md",
      "name": "README.md",
      "size": 2048,
      "last_modified": "2024-01-10T08:00:00Z",
      "content_type": "text/markdown"
    }
  ],
  "file_count": 1,
  "next_cursor": null
}
```

**Step 2: User clicks "reports/" folder → Use `prefix` from folder object**

```
GET /knowledge/kb-main/sources/company-s3/files?prefix=reports/
```

```json
{
  "source_id": "company-s3",
  "source_name": "Company Documents",
  "prefix": "reports/",
  "folders": [
    { "prefix": "reports/2023/", "name": "2023", "is_empty": false },
    { "prefix": "reports/2024/", "name": "2024", "is_empty": false }
  ],
  "files": [
    {
      "key": "reports/annual-summary.pdf",
      "name": "annual-summary.pdf",
      "size": 102400,
      "last_modified": "2024-01-15T10:30:00Z",
      "content_type": "application/pdf"
    }
  ],
  "file_count": 1,
  "next_cursor": null
}
```

**Step 3: User clicks "2024/" folder → Use `prefix` from folder object**

```
GET /knowledge/kb-main/sources/company-s3/files?prefix=reports/2024/
```

```json
{
  "source_id": "company-s3",
  "source_name": "Company Documents",
  "prefix": "reports/2024/",
  "folders": [],
  "files": [
    {
      "key": "reports/2024/q1-report.pdf",
      "name": "q1-report.pdf",
      "size": 256000,
      "last_modified": "2024-04-01T09:00:00Z",
      "content_type": "application/pdf"
    },
    {
      "key": "reports/2024/q2-report.pdf",
      "name": "q2-report.pdf",
      "size": 245000,
      "last_modified": "2024-07-01T09:00:00Z",
      "content_type": "application/pdf"
    },
    {
      "key": "reports/2024/q3-report.pdf",
      "name": "q3-report.pdf",
      "size": 260000,
      "last_modified": "2024-10-01T09:00:00Z",
      "content_type": "application/pdf"
    }
  ],
  "file_count": 3,
  "next_cursor": null
}
```

**FE Navigation Logic:**

```typescript
interface Folder {
  prefix: string;  // Use this for the next request
  name: string;    // Display this in the UI
  is_empty: boolean;
}

// When user clicks a folder
function onFolderClick(folder: Folder) {
  // folder.prefix contains the full path to request
  fetchFiles(knowledgeId, sourceId, folder.prefix);
}

// Breadcrumb navigation
function goToPath(path: string) {
  // path is the prefix value (e.g., "reports/2024/")
  fetchFiles(knowledgeId, sourceId, path);
}

async function fetchFiles(knowledgeId: string, sourceId: string, prefix: string = "") {
  const url = `/knowledge/${knowledgeId}/sources/${sourceId}/files?prefix=${encodeURIComponent(prefix)}`;
  const response = await fetch(url);
  return response.json();
}
```

### Errors

| Status | Description |
|--------|-------------|
| `404` | Knowledge base or content source not found |
| `400` | Invalid cursor token |

---

## 3. Add Content from Source

**POST** `/knowledge/{knowledge_id}/content/from-source`

Add a single file from a content source to the knowledge base.

### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `knowledge_id` | string | Yes | ID of the knowledge base |

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
| `404` | Knowledge base or content source not found |
| `400` | Invalid file key or source configuration error |

---


## UI Workflow Example

### Basic Flow with Folder Navigation

```
1. Page Load (user has selected a knowledge base)
   ↓
   GET /knowledge/kb-main/sources
   → Display source dropdown

2. User Selects Source "company-s3"
   ↓
   GET /knowledge/kb-main/sources/company-s3/files
   → Display root folders and files
   → Response: { folders: [{prefix: "reports/", name: "reports", is_empty: false}], files: [...] }

3. User Clicks "reports/" Folder
   ↓
   GET /knowledge/kb-main/sources/company-s3/files?prefix=reports/
   → Display subfolders (2023/, 2024/) and files in reports/
   → Response: { folders: [{prefix: "reports/2024/", name: "2024", is_empty: false}], files: [...] }

4. User Clicks "2024/" Folder
   ↓
   GET /knowledge/kb-main/sources/company-s3/files?prefix=reports/2024/
   → Display files in reports/2024/
   → Response: { folders: [], files: [...], next_cursor: null }

5. User Selects 3 Files and Clicks "Add"
   ↓
   POST /knowledge/kb-main/content/from-source/batch
   {
     "source_id": "company-s3",
     "keys": ["reports/2024/q1.pdf", "reports/2024/q2.pdf", "reports/2024/q3.pdf"]
   }
   → Show "3 files queued for processing"

6. Poll for Status (existing endpoint)
   ↓
   GET /knowledge/kb-main/content/{content_id}/status
   → Update progress UI
```

### Pagination Flow (Large Directories)

```
1. Initial Load of Large Folder
   ↓
   GET /knowledge/kb-main/sources/company-s3/files?prefix=logs/&limit=100
   → Response: { files: [...100 files...], next_cursor: "abc123" }
   → Display first 100 files with "Load More" button

2. User Clicks "Load More"
   ↓
   GET /knowledge/kb-main/sources/company-s3/files?prefix=logs/&limit=100&cursor=abc123
   → Response: { files: [...next 100 files...], next_cursor: "def456" }
   → Append files to list

3. User Clicks "Load More" Again
   ↓
   GET /knowledge/kb-main/sources/company-s3/files?prefix=logs/&limit=100&cursor=def456
   → Response: { files: [...final 50 files...], next_cursor: null }
   → Append files, hide "Load More" button
```

### FE Pagination Logic

```typescript
// Simple check for more pages
const hasMore = response.next_cursor !== null;

// Load more handler
async function loadMore() {
  const response = await fetch(
    `/knowledge/${knowledgeId}/sources/${sourceId}/files?prefix=${prefix}&cursor=${nextCursor}`
  );
  const data = await response.json();
  
  files = [...files, ...data.files];
  nextCursor = data.next_cursor;  // null when done
}
```

---

## Content Source Types

| Type | Description | Key Format |
|------|-------------|------------|
| `s3` | AWS S3 bucket | `path/to/file.pdf` |
| `gcs` | Google Cloud Storage | `path/to/file.pdf` |
| `sharepoint` | Microsoft SharePoint | `Library/Folder/file.docx` |
| `github` | GitHub repository | `path/to/file.md` |

---

## Design Notes

### URL Structure

All endpoints are scoped under a knowledge base:

```
/knowledge/{knowledge_id}/sources
/knowledge/{knowledge_id}/sources/{source_id}/files
/knowledge/{knowledge_id}/content/from-source
```

This makes the ownership hierarchy explicit:
- A **knowledge base** has multiple **content sources**
- A **content source** has multiple **files**
- **Content** is added to a specific **knowledge base**

### Cursor Implementation

The `cursor` parameter is **source-agnostic**. The backend:
1. Receives the opaque cursor string from the client
2. Passes it directly to the underlying source's native pagination mechanism
3. Returns the source's next continuation token as `next_cursor`

Each source type uses its native pagination:
- **S3**: `ContinuationToken`
- **GCS**: `page_token`  
- **SharePoint**: `$skiptoken`
- **GitHub**: Link header cursor

The client treats the cursor as an opaque string — never parse or construct it.

### Folder Metadata

File counts per folder are **not provided** because:
- S3/GCS are flat object stores with no folder metadata
- Getting counts requires listing all objects (expensive)
- `is_empty` is provided as a cheap alternative (single API call with `MaxKeys=1`)

For sources that support folder metadata natively (SharePoint, GitHub), additional fields may be included in future versions.
