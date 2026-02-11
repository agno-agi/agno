# External Media Storage

## Problem

When media (images, audio, video, files) is attached to agent messages in Agno, it gets converted to base64 and stored inline in the JSONB `runs` column of `agno_sessions`. This causes massive database bloat — users have reported 165MB sessions from just 16 image messages, and tables growing to 4GB+. See [issue #5741](https://github.com/agno-agi/agno/issues/5741).

## Solution

A `MediaStorage` abstraction that uploads media to external object storage (S3, local filesystem, or any S3-compatible service) **before** database persistence. Only lightweight `MediaReference` objects are stored in the database. The model API still receives full content at runtime, and frontends get accessible URLs instead of inline blobs.

## How It Works

### Storage Flow

```
Agent run completes
  -> cleanup_and_store()
    -> offload_run_media()          # NEW: upload bytes to S3/local
      -> attach MediaReference      # lightweight ref with storage_key + URL
      -> clear content bytes        # no more base64 in memory
    -> scrub_run_output_for_storage()  # existing scrub logic
    -> upsert to DB                 # DB now stores references, not blobs
```

### Retrieval Flow

```
DB load -> from_dict() detects "media_reference" key
  -> creates media object with url=presigned_url
  -> Frontend displays via URL (zero S3 API calls)
  -> LLM receives URL directly (most providers accept URLs)
```

### History Handling

When `add_history_to_context=True`, messages from previous runs are loaded from DB. Media references are automatically detected during deserialization, and pre-signed URLs are refreshed before sending to the LLM. This is a local computation (no S3 API call), so there is zero performance cost.

## Configuration

```python
from agno.agent import Agent
from agno.media_storage.s3 import S3MediaStorage

storage = S3MediaStorage(
    bucket="my-agno-media",
    region="us-east-1",
    presigned_url_expiry=3600,
)

agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=PostgresDb(db_url="postgresql+psycopg://..."),
    media_storage=storage,          # NEW
)
```

| `store_media` | `media_storage` | Behavior |
|---|---|---|
| `True` (default) | `None` (default) | Unchanged: base64 in DB |
| `True` | Configured | **New**: upload to storage, references in DB |
| `False` | Any | Media stripped (existing behavior) |

## Backward Compatibility

- Old sessions with base64 data and new sessions with references coexist seamlessly — no migration needed
- `from_dict()` detects the presence of `media_reference` in serialized data and reconstructs accordingly
- If `media_storage` is not configured, everything works exactly as before

## What Changed

### New Files

| File | Purpose |
|---|---|
| `agno/media_storage/__init__.py` | Package exports |
| `agno/media_storage/base.py` | `MediaStorage` and `AsyncMediaStorage` abstract base classes |
| `agno/media_storage/reference.py` | `MediaReference` pydantic model |
| `agno/media_storage/s3.py` | S3 backend (boto3, supports MinIO/DigitalOcean Spaces via `endpoint_url`) |
| `agno/media_storage/async_s3.py` | Async S3 backend (aioboto3) |
| `agno/media_storage/local.py` | Local filesystem backend (for development/testing) |
| `agno/utils/media_offload.py` | Offload orchestration, URL refresh utilities |
| `cookbook/06_storage/media_storage_s3.py` | S3 usage example |
| `cookbook/06_storage/media_storage_local.py` | Local storage usage example |
| `tests/unit/media_storage/` | 39 unit tests covering all components |

### Modified Files

| File | Change |
|---|---|
| `agno/media.py` | Added `media_reference` and `metadata` fields to Image, Audio, Video, File. Updated validators, `to_dict()`, and `get_content_bytes()`. |
| `agno/utils/media.py` | Updated `reconstruct_*_from_dict()` functions to detect and handle `media_reference`. |
| `agno/models/message.py` | Updated all 7 inline reconstruction blocks in `Message.from_dict()`. |
| `agno/agent/agent.py` | Added `media_storage` field. |
| `agno/agent/_run.py` | Injected offload in `cleanup_and_store()` and `acleanup_and_store()`. |
| `agno/agent/_messages.py` | Auto-refresh media URLs when loading history. |
| `agno/team/team.py` | Added `media_storage` field. |
| `agno/team/_init.py` | Added `media_storage` parameter and assignment. |
| `agno/team/_run.py` | Injected offload in team cleanup functions. |
| `agno/team/_messages.py` | Auto-refresh media URLs when loading team history. |
| `agno/team/_session.py` | Added member response offloading before scrubbing. |
| `pyproject.toml` | Added `media-storage-s3 = ["boto3", "aioboto3"]` optional dependency. |

## Design Decisions

### Error Isolation

Media offload is wrapped in `try/except`. If S3 is unreachable, the run still saves to the database with inline content — the user's run is never lost due to a storage failure.

### Sync/Async Type Checking

`MediaStorage` is for sync `run()`, `AsyncMediaStorage` is for async `arun()`. A mismatch logs a warning and skips offload rather than crashing.

### No Duplicate Uploads

- Media that already has a `media_reference` is skipped
- Messages tagged `from_history=True` are skipped
- URL-only media (no content bytes) is skipped
- `File` objects with `external` set (provider-managed, e.g. GeminiFile) are skipped

### Full Field Preservation

When `media_reference` is set, `to_dict()` emits all class-specific fields (format, detail, width, height, transcript, etc.) alongside the reference. Nothing is lost during serialization.

## Known Limitations (v1)

1. **Pre-signed URL expiry in AgentOS UI**: URLs stored at offload time may expire before viewed. Set a long `presigned_url_expiry` or call `refresh_media_urls()` manually.
2. **Single storage backend per refresh**: `refresh_media_urls()` accepts one storage instance. Mixed backends within a session are not refreshed automatically.
3. **No automatic propagation**: `media_storage` does not propagate from Team to member agents. Configure each independently, or rely on team-level offloading for `member_responses`.
4. **Sync/async must match**: Use `MediaStorage` with `run()`, `AsyncMediaStorage` with `arun()`.

## Installation

```bash
# For S3 support
pip install 'agno[media-storage-s3]'

# Local storage needs no extra dependencies
```
