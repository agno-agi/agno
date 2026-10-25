# PostgreSQL Integration

Examples demonstrating PostgreSQL database integration with Agno agents, teams, and workflows.

## Setup

```shell
uv pip install "psycopg[binary]"
```

## Configuration

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://username:password@localhost:5432/database")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Async usage

Agno also supports using your PostgreSQL database asynchronously, via the `AsyncPostgresDb` class:

```python
from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb

db = AsyncPostgresDb(db_url="postgresql+psycopg://username:password@localhost:5432/database")

agent = Agent(
    db=db,
    add_history_to_context=True,
)
```

## Examples

- [`postgres_for_agent.py`](postgres_for_agent.py) - Agent with PostgreSQL storage
- [`postgres_for_team.py`](postgres_for_team.py) - Team with PostgreSQL storage
- [`postgres_for_workflow.py`](postgres_for_workflow.py) - Workflow with PostgreSQL storage

## Shared engine configuration

Use `create_postgres_engine` when storage and application SQL need the same pool:

```python
from agno.db.postgres import PostgresDb, create_postgres_engine
from agno.fs.db import DbFileSystem

engine = create_postgres_engine(
    "postgresql://username:password@localhost:5432/database",
    connect_args={"connect_timeout": 5},
)
db = PostgresDb(id="app-db", db_engine=engine)
files = DbFileSystem(db=db, table_name="agent_files", db_schema="ai")
```

The factory supplies pre-ping, a 3,600-second recycle interval and Agno's JSON
serializer. SQLAlchemy keyword arguments override those defaults. Plain
`postgres://` and `postgresql://` URLs select Psycopg 3; explicit drivers and TLS
parameters are preserved. Existing `PostgresDb(db_url=...)` and
`AsyncPostgresDb(db_url=...)` driver selection remains unchanged; the convenience
normalization applies to the new factories. Use a SQLAlchemy `URL` object to supply unescaped
credentials. Each call creates a separate pool, so create and reuse one engine.

`create_async_postgres_engine` accepts the same options and returns an
`AsyncEngine` for `AsyncPostgresDb(db_engine=engine)`. Engine construction is
synchronous and opens no connection; database operations use `await`.

Constructing `PostgresDb` from an engine keeps the connection URL out of its
serialized configuration. Register and reuse that live database instance when
loading components; the serialized config cannot recreate its connection.
TLS certificates and provider-specific pooling constraints remain deployment
configuration. In particular, page sync requires session affinity for its
advisory lock and cannot use a transaction pooler.

- [`shared_engine.py`](shared_engine.py) - Configure and share a pool without connecting
