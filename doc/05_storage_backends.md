# Storage & Session Backends

Agno uses a **storage backend** (`db=`) to persist agent sessions, conversation history, memories, run state, and approval records. 13+ backends are supported.

**Directory:** `libs/agno/agno/db/`

---

## What gets stored

| Data | Table / Collection | Notes |
|------|--------------------|-------|
| Agent sessions | `agent_sessions` | Chat history, session state, cached messages |
| Team sessions | `team_sessions` | Team conversation and member state |
| Workflow sessions | `workflow_sessions` | Step execution state, resume points |
| User memories | `memories` | Cross-session persistent facts |
| Agent runs | `agent_runs` | Run metadata, token counts, status |
| Approval records | `approvals` | Pending / resolved human-in-the-loop items |

---

## Unified interface

All backends implement the same `Database` base class:

```python
class Database:
    def read_session(self, session_id, user_id) -> Session | None: ...
    def upsert_session(self, session) -> Session: ...
    def delete_session(self, session_id) -> None: ...
    def get_sessions(self, user_id, num_sessions) -> list[Session]: ...
    def read_memory(self, user_id) -> UserMemory | None: ...
    def upsert_memory(self, user_id, memories) -> None: ...
    def get_approvals(self, status) -> tuple[list, int]: ...
    def update_approval(self, approval_id, ...) -> dict: ...
```

---

## Backends

### PostgreSQL (recommended for production)

**Module:** `agno.db.postgres`

```python
from agno.db.postgres import PostgresDb
from agno.agent import Agent

db = PostgresDb(
    table_name="agent_sessions",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

agent = Agent(model=..., db=db, session_id="user-42")
```

Custom table names for each agent:

```python
db_sales   = PostgresDb(table_name="sales_agent_sessions",   db_url=URL)
db_support = PostgresDb(table_name="support_agent_sessions", db_url=URL)
```

Async variant:

```python
from agno.db.async_postgres import AsyncPostgresDb

db = AsyncPostgresDb(table_name="sessions", db_url=URL)
```

---

### SQLite (development / single-node)

**Module:** `agno.db.sqlite`

```python
from agno.db.sqlite import SqliteDb

db = SqliteDb(
    db_file="tmp/agent.db",
    session_table="agent_sessions",
    approvals_table="approvals",  # optional, for approval storage
)

agent = Agent(model=..., db=db)
```

No server required — stores everything in a single `.db` file.

---

### MySQL / MariaDB

**Module:** `agno.db.mysql`

```python
from agno.db.mysql import MysqlDb

db = MysqlDb(
    table_name="agent_sessions",
    db_url="mysql+pymysql://user:pass@localhost:3306/agno",
)
```

---

### MongoDB

**Module:** `agno.db.mongo`

```python
from agno.db.mongo import MongoDb

db = MongoDb(
    collection_name="agent_sessions",
    db_url="mongodb://localhost:27017",
    db_name="agno",
)
```

---

### AWS DynamoDB

**Module:** `agno.db.dynamo`

```python
from agno.db.dynamo import DynamoDb

db = DynamoDb(
    table_name="agent_sessions",
    region_name="us-east-1",
)
```

Uses IAM credentials from environment or instance role. No API keys needed.

---

### Redis

**Module:** `agno.db.redis`

```python
from agno.db.redis import RedisDb

db = RedisDb(
    prefix="agno:sessions",
    host="localhost",
    port=6379,
    db=0,
    ttl=86400,  # session TTL in seconds
)
```

---

### Google Firestore

**Module:** `agno.db.firestore`

```python
from agno.db.firestore import FirestoreDb

db = FirestoreDb(
    collection_name="agent_sessions",
    project_id="my-gcp-project",
)
```

---

### Google Cloud Storage (JSON)

**Module:** `agno.db.gcs_json`

Stores each session as a JSON file in a GCS bucket. Useful for simple serverless deployments:

```python
from agno.db.gcs_json import GcsJsonDb

db = GcsJsonDb(
    bucket_name="my-agent-sessions",
    prefix="sessions/",
)
```

---

### SurrealDB

**Module:** `agno.db.surrealdb`

```python
from agno.db.surrealdb import SurrealDb

db = SurrealDb(
    table_name="agent_sessions",
    url="http://localhost:8000",
    namespace="agno",
    database="production",
)
```

---

### SingleStore

**Module:** `agno.db.singlestore`

```python
from agno.db.singlestore import S2Db

db = S2Db(
    table_name="agent_sessions",
    db_url="mysql+pymysql://user:pass@host:3306/agno",
)
```

---

### JSON files (simple local)

**Module:** `agno.db.json`

Stores sessions as JSON files on the local filesystem. Useful for quick scripting:

```python
from agno.db.json import JsonDb

db = JsonDb(path="./sessions/")
```

---

### In-Memory (testing only)

**Module:** `agno.db.in_memory`

No persistence — data is lost when the process exits:

```python
from agno.db.in_memory import InMemoryDb

db = InMemoryDb()
agent = Agent(model=..., db=db)  # good for unit tests
```

---

## Schema migrations

Agno manages table schema via its migration system. Create tables automatically:

```python
db = PostgresDb(table_name="sessions", db_url=URL)
db.create()  # creates the table if it doesn't exist
```

Or use the AgentOS migration endpoint:

```
POST /database/migrate
```

---

## Session isolation patterns

### Per-user isolation

```python
agent = Agent(
    model=...,
    db=db,
    session_id="chat",
    user_id="user-123",          # sessions are scoped to this user
)
```

### Per-conversation isolation

```python
import uuid

agent = Agent(
    model=...,
    db=db,
    session_id=str(uuid.uuid4()),  # unique session per conversation
    add_history_to_messages=True,
    num_history_runs=20,
)
```

### Shared sessions (e.g. team channels)

```python
agent = Agent(
    model=...,
    db=db,
    session_id="team-general-channel",  # shared by all users in the channel
    user_id=None,
)
```

---

## Selection guide

| Use case | Recommended backend |
|----------|---------------------|
| Production, SQL infra | PostgreSQL |
| Development / local testing | SQLite |
| Already on MongoDB | MongoDB |
| AWS serverless | DynamoDB |
| Low-latency caching layer | Redis |
| GCP serverless | Firestore or GCS JSON |
| Unit tests | In-Memory |
| MariaDB / Frappe stack | MySQL |

---

## Configuring tables separately per agent

```python
from agno.db.postgres import PostgresDb

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Each agent gets its own table to avoid schema conflicts
weather_agent = Agent(db=PostgresDb(table_name="weather_sessions", db_url=DB_URL))
finance_agent = Agent(db=PostgresDb(table_name="finance_sessions", db_url=DB_URL))
```

---

## Storing approvals

The SQLite and PostgreSQL backends also store approval records (for human-in-the-loop flows):

```python
from agno.db.sqlite import SqliteDb

db = SqliteDb(
    db_file="tmp/agent.db",
    session_table="sessions",
    approvals_table="approvals",
)

# Query pending approvals
pending, total = db.get_approvals(status="pending")

# Resolve an approval
db.update_approval(
    approval_id="...",
    expected_status="pending",
    status="approved",
    resolved_by="alice",
    resolved_at=int(time.time()),
)
```
