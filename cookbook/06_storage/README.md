# Database Integration

This directory contains examples demonstrating how to integrate various databases with Agno agents, teams, and workflows for persistent storage.

## Setup

```shell
# Install required database drivers based on your choice
uv pip install psycopg2-binary  # PostgreSQL
uv pip install pymongo         # MongoDB
uv pip install mysql-connector-python  # MySQL
uv pip install redis           # Redis
uv pip install valkey-glide-sync  # Valkey
uv pip install google-cloud-firestore  # Firestore
uv pip install boto3           # DynamoDB
uv pip install singlestoredb   # SingleStore
uv pip install google-cloud-storage  # GCS
```

Navigate to the specific integration directory for detailed documentation and examples.

## Basic Integration

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://user:password@localhost:5432/dbname")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Supported Databases

- [`postgres`](postgres/) - PostgreSQL relational database integration
- [`sqlite`](sqlite/) - SQLite lightweight database integration
- [`mongo`](mongo/) - MongoDB document database integration
- [`mysql`](mysql/) - MySQL relational database integration
- [`redis`](redis/) - Redis in-memory data structure store integration
- [`valkey`](valkey/) - Valkey in-memory data structure store integration
- [`singlestore`](singlestore/) - SingleStore distributed SQL database integration
- [`firestore`](firestore/) - Google Cloud Firestore NoSQL database integration
- [`dynamodb`](dynamodb/) - AWS DynamoDB NoSQL database integration
- [`json_db`](json_db/) - JSON file-based storage integration
- [`gcs`](gcs/) - Google Cloud Storage JSON blob integration
- [`in_memory`](in_memory/) - In-memory storage with optional persistence hooks

## Session Management

- [`in_memory_storage_for_agent.py`](in_memory/in_memory_storage_for_agent.py) - Basic session handling
- [`01_persistent_session_storage.py`](01_persistent_session_storage.py) - Database persistence
- [`02_session_summary.py`](02_session_summary.py) - Session summarization
- [`03_chat_history.py`](03_chat_history.py) - Chat history management
- [`04_session_summary_limits.py`](04_session_summary_limits.py) - Session summary limits (last_n_runs / conversation_limit)

## Media Storage

Offload media content (images, audio, video, files) to external storage and keep only lightweight references in the database.

The S3 and GCS backends need their optional dependencies:

```shell
uv pip install 'agno[s3]'   # S3 (boto3 + aioboto3)
uv pip install 'agno[gcs]'  # GCS (google-cloud-storage)
```

- [`05_media_storage_local.py`](05_media_storage_local.py) - Offload media to the local filesystem (LocalMediaStorage)
- [`06_media_storage_s3.py`](06_media_storage_s3.py) - Offload media to S3-compatible object storage (S3MediaStorage)
- [`07_media_storage_multiturn.py`](07_media_storage_multiturn.py) - Multi-turn media reuse: offload on turn 1, reference reloaded on turn 2
- [`08_media_storage_gcs.py`](08_media_storage_gcs.py) - Offload media to Google Cloud Storage (GCSMediaStorage)
- [`09_media_storage_delete.py`](09_media_storage_delete.py) - Delete a session's stored objects along with its rows (delete_media=True)
- [`10_media_storage_workflow.py`](10_media_storage_workflow.py) - Offload media across a workflow's steps (S3)
- [`11_media_storage_file_generation.py`](11_media_storage_file_generation.py) - Offload files the agent generates, and read one back with get_content_bytes(storage=...)

### Enable this only after the whole fleet is upgraded

Turning media storage on is a one-way door. There is no schema change — no new table, no new
column, no migration — but the shape of the media inside the existing column changes: an
offloaded image carries a `media_reference` and no `content`.

A reader that predates this feature validates that media has one of `url`, `filepath`, or
`content`, and an offloaded image has none of the three. It does not skip that image, it
raises — so one offloaded row makes `get_sessions()` fail for the whole session list,
including clean sessions written before the upgrade.

New code reads old rows fine, so the upgrade direction is safe. The rollback direction is not.
Roll the release out everywhere first, then enable `media_storage` — and expect that once rows
carry references, going back to an older build leaves that media unreadable until you return.
