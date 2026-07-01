# Database Integration

This directory contains examples demonstrating how to integrate various databases with Agno agents, teams, and workflows for persistent storage.

## Setup

```shell
# Install required database drivers based on your choice
uv pip install psycopg2-binary  # PostgreSQL
uv pip install pymongo         # MongoDB
uv pip install mysql-connector-python  # MySQL
uv pip install redis           # Redis
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

- [`05_media_storage_local.py`](05_media_storage_local.py) - Offload media to the local filesystem (LocalMediaStorage)
- [`06_media_storage_s3.py`](06_media_storage_s3.py) - Offload media to S3-compatible object storage (S3MediaStorage)
- [`07_media_storage_multiturn.py`](07_media_storage_multiturn.py) - Multi-turn media reuse with store_media=False
