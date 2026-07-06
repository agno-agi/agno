# Turso (libSQL) Integration

Examples demonstrating Turso / libSQL database integration with Agno agents.

[Turso](https://turso.tech) is a managed database service built on [libSQL](https://github.com/tursodatabase/libsql) — an open-source fork of SQLite. Useful properties for agentic workloads:

- **Per-agent / per-session databases at scale** — Turso paid plans support unlimited active databases, so you can spin up an isolated database per agent session.
- **MVCC concurrent writes** — multiple agents can write to the same database without lock contention.
- **Embedded replicas** — sync a remote Turso database into a local file for low-latency reads.

## Configuration

### Remote Turso database

```python
import os
from agno.agent import Agent
from agno.db.turso import TursoDb

db = TursoDb(
    url=os.environ["TURSO_DATABASE_URL"],
    auth_token=os.environ["TURSO_AUTH_TOKEN"],
)

agent = Agent(db=db, add_history_to_context=True)
```

`TURSO_DATABASE_URL` should look like `libsql://<your-db>-<org>.turso.io`. Both `libsql://` and `https://` schemes (and bare hostnames) are accepted.

### Embedded replica (local file synced from remote)

```python
db = TursoDb(
    db_file="./local.db",
    sync_url=os.environ["TURSO_DATABASE_URL"],
    auth_token=os.environ["TURSO_AUTH_TOKEN"],
)
```

### Local libSQL file (no remote)

```python
db = TursoDb(db_file="./local.db")
```

## Setup

```bash
pip install sqlalchemy-libsql

# Install the Turso CLI (https://docs.turso.tech/cli/installation)
turso db create my-agno-db
export TURSO_DATABASE_URL="$(turso db show --url my-agno-db)"
export TURSO_AUTH_TOKEN="$(turso db tokens create my-agno-db)"
```

## Async usage

`AsyncTursoDb` is not yet provided. The upstream `sqlalchemy-libsql` dialect does not currently expose a working async DBAPI driver; once it does, an `AsyncTursoDb` will be added.

## Platform support

`sqlalchemy-libsql` ships precompiled wheels for Linux and macOS only. Windows is not supported at this time.

## Examples

- [`turso_for_agent.py`](turso_for_agent.py) — Agent with Turso storage
