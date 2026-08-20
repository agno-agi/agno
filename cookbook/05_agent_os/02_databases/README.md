# 02 Databases

Pass a database to `AgentOS(db=...)` to make it the default for agents, teams,
and workflows that do not provide their own database. Use SQLite for local
development and Postgres for production; the reference table below covers
other supported storage adapters without repeating the same AgentOS example.

## Files

| File | Description |
|---|---|
| `basic.py` | Demonstrates default-database inheritance and automatic table provisioning with SQLite. |
| `postgres.py` | Selects a synchronous or asynchronous Postgres adapter for production persistence. |
| `surreal.py` | Shows SurrealDB's client, credentials, namespace, and database constructor shape. |
| `s3_media_storage.py` | Offloads media bytes to S3 so the database keeps only a MediaReference. |
| `gcs_media_storage.py` | Offloads media bytes to GCS so the database keeps only a MediaReference. |
| `media_storage_delete.py` | Reads session media back through the media route, and deletes the objects with the session. |

## Default database and provisioning

`AgentOS` assigns its database to each listed agent, team, and workflow whose
own `db` is unset. A component-level database always takes precedence.
`auto_provision_dbs=True` is the default and creates the required tables during
server startup; disable it only when an external migration process owns the
schema.

## Backend reference

| Backend | Import | Connection | Required service |
|---|---|---|---|
| SQLite | `from agno.db.sqlite import SqliteDb` | `SqliteDb(db_file="tmp/agent_os.db")` | None |
| JSON | `from agno.db.json import JsonDb` | `JsonDb(db_path="tmp/agent_os_json")` | None |
| Postgres | `from agno.db.postgres import PostgresDb` | `PostgresDb(db_url="postgresql+psycopg://user:pass@host:5432/db")` | PostgreSQL |
| MySQL | `from agno.db.mysql import MySQLDb` | `MySQLDb(db_url="mysql+pymysql://user:pass@host:3306/db")` | MySQL |
| MongoDB | `from agno.db.mongo import MongoDb` | `MongoDb(db_url="mongodb://localhost:27017", db_name="agno")` | MongoDB |
| Redis | `from agno.db.redis import RedisDb` | `RedisDb(db_url="redis://localhost:6379/0")` | Redis |
| Valkey | `from agno.db.valkey import ValkeyDb` | `ValkeyDb(host="localhost", port=6379)` | Valkey |
| DynamoDB | `from agno.db.dynamo import DynamoDb` | `DynamoDb()` | AWS DynamoDB and `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` |
| Firestore | `from agno.db.firestore import FirestoreDb` | `FirestoreDb(project_id="my-project")` | Firestore and Application Default Credentials |
| GCS JSON | `from agno.db.gcs_json import GcsJsonDb` | `GcsJsonDb(bucket_name="my-bucket")` | GCS and Application Default Credentials |
| SingleStore | `from agno.db.singlestore import SingleStoreDb` | `SingleStoreDb(db_url="mysql+pymysql://user:pass@host:3306/db")` | SingleStore |
| SurrealDB | `from agno.db.surrealdb import SurrealDb` | `SurrealDb(client=None, db_url=..., db_creds=..., db_ns=..., db_db=...)` | SurrealDB |
| ClickHouse | `from agno.db.clickhouse import ClickhouseDb` | `ClickhouseDb(host="localhost", database="agno")` | **Traces only; not a general AgentOS persistence backend** |
| In-memory | `from agno.db.in_memory import InMemoryDb` | `InMemoryDb()` | None; process-local and non-durable |

Neon and Supabase use the Postgres wire protocol, so pass their connection
strings to `PostgresDb` rather than using a separate adapter. For asynchronous
Postgres, import `AsyncPostgresDb` and use a
`postgresql+psycopg_async://...` URL.

ClickHouse implements the trace and span surface. Use a row store such as
Postgres for sessions, memories, knowledge, evals, and components.

## External media storage

The database above stores the conversation; `media_storage` decides where the
file bytes go. Pass a backend to `AgentOS(media_storage=...)` and uploaded and
generated files are written to object storage, leaving a `MediaReference` in the
session row instead of base64. Media is then served through
`GET /sessions/{session_id}/media/{storage_key}`.

| Backend | Import | Connection | Required service |
|---|---|---|---|
| Local | `from agno.media.storage.local import LocalMediaStorage` | `LocalMediaStorage(base_path="tmp/media")` | None |
| S3 | `from agno.media.storage.s3 import S3MediaStorage` | `S3MediaStorage(bucket="my-bucket")` | S3 and `agno[s3]` |
| GCS | `from agno.media.storage.gcs import GCSMediaStorage` | `GCSMediaStorage(bucket="my-bucket")` | GCS and `agno[gcs]` |

Each backend has an `Async` counterpart for asynchronous applications.

Pass `region` when the bucket is not in the default region: uploads find the right
region on their own, but the media URL carries the region in its signature, so
without it media saves cleanly and then fails to load.

## Prerequisites

- All examples need `OPENAI_API_KEY` only when an agent run calls the model.
- Start Postgres with `./cookbook/scripts/run_pgvector.sh`.
- Install `agno[surrealdb]` and start SurrealDB with
  `./cookbook/scripts/run_surrealdb.sh`.
- Install `agno[s3]` and set `AGNO_FILE_OUTPUT_S3_BUCKET` plus AWS credentials
  for `s3_media_storage.py` and `media_storage_delete.py`.
- Install `agno[gcs]`, set `AGNO_FILE_OUTPUT_GCS_BUCKET`, and authenticate with
  Google Cloud Application Default Credentials for `gcs_media_storage.py`.

## Run

SQLite:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/02_databases/basic.py
```

Synchronous Postgres:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/02_databases/postgres.py
```

Asynchronous Postgres:

```bash
AGENTOS_USE_ASYNC_POSTGRES=true \
  .venvs/demo/bin/python cookbook/05_agent_os/02_databases/postgres.py
```

SurrealDB:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/02_databases/surreal.py
```

S3 media storage:

```bash
AGNO_FILE_OUTPUT_S3_BUCKET=my-bucket \
  .venvs/demo/bin/python cookbook/05_agent_os/02_databases/s3_media_storage.py
```

GCS media storage:

```bash
AGNO_FILE_OUTPUT_GCS_BUCKET=my-bucket \
  .venvs/demo/bin/python cookbook/05_agent_os/02_databases/gcs_media_storage.py
```

Reading and deleting session media:

```bash
AGNO_FILE_OUTPUT_S3_BUCKET=my-bucket \
  .venvs/demo/bin/python cookbook/05_agent_os/02_databases/media_storage_delete.py
```

Each server listens on port 7777. Read its database ID from `GET /config`, then
run a schema migration with:

```bash
curl -X POST http://localhost:7777/databases/<db-id>/migrate
```

To migrate to a specific schema version, add
`?target_version=<version>` to the URL.
