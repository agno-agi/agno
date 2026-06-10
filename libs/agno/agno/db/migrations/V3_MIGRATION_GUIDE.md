# Agno v3.0 Storage Migration Guide: Normalized Runs Table

## Overview

Agno v3.0 changes how session runs are stored. Runs are no longer kept as a JSON blob
inside the sessions table — each run is now stored as its own row in a dedicated runs
table (`agno_runs` by default).

### The problem (v2.x)

In v2.x, the `agno_sessions.runs` column held the full list of runs (with all their
messages) as a single JSON value:

- **Write amplification**: every save rewrote the entire runs blob. Saving run N wrote
  runs 1..N again, so the total bytes written over a session's life grew quadratically.
- **Unbounded row size**: long-lived sessions reached tens or hundreds of MB in a single
  row, slowing down every read/write and eventually causing upsert failures.
- **No partial reads**: fetching the last few runs required loading and parsing the
  entire blob.

### The solution (v3.0)

Runs are stored one-row-per-run in the runs table:

```
agno_runs
├── run_id        TEXT PRIMARY KEY
├── session_id    TEXT NOT NULL (indexed)
├── run_type      TEXT NOT NULL  -- "agent" | "team" | "workflow"
├── agent_id      TEXT (indexed)
├── team_id       TEXT (indexed)
├── workflow_id   TEXT (indexed)
├── user_id       TEXT (indexed)
├── parent_run_id TEXT           -- set for team member runs
├── status        TEXT (indexed)
├── run_index     BIGINT         -- position of the run within its session
├── run_data      JSONB / JSON   -- the full run payload (messages, tools, metrics, ...)
└── created_at / updated_at
```

- Each run is written once (plus an update when it changes, e.g. paused → completed).
  Saving a new run no longer touches previous runs.
- Session rows stay small: the `runs` column is removed from `agno_sessions`.
- Runs can be queried directly (by session, agent, status, ...) without loading sessions.

The fields you filter on (`status`, `agent_id`, `session_id`, ...) are real columns; the
run payload stays as a single JSON value because a run is always read and written as a
unit.

## Supported databases

v3.0 normalized run storage is implemented for:

- `PostgresDb` and `AsyncPostgresDb`
- `SqliteDb` and `AsyncSqliteDb`

Other adapters (MySQL, MongoDB, Redis, DynamoDB, Firestore, SingleStore, SurrealDB,
JSON, GCS, in-memory) continue to store runs inline in the session and will be ported in
follow-up releases.

## Migrating existing data

### Option 1: Run the v3.0.0 migration (recommended)

The migration creates the runs table, moves every run out of the `runs` blobs, and drops
the `runs` column from the sessions table.

```python
import asyncio

from agno.db.migrations.manager import MigrationManager
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://...")

# Migrates all tables to the latest schema version (3.0.0)
asyncio.run(MigrationManager(db).up())
```

The migration is idempotent: already-migrated runs are skipped (`ON CONFLICT DO
NOTHING`), and it is a no-op when the `runs` column no longer exists.

To revert (rebuilds the blobs from the runs table and drops the runs table):

```python
asyncio.run(MigrationManager(db).down(target_version="2.5.6"))
```

### Option 2: Do nothing (lazy migration)

v3.0 also works against an unmigrated database:

- Reads fall back to the legacy `runs` column when a session has no rows in the runs
  table yet.
- The first time a session is saved after upgrading, all of its runs are written to the
  runs table and the legacy blob is cleared for that session.

This means active sessions migrate themselves over time. The explicit migration is still
recommended to migrate dormant sessions and reclaim the space of the `runs` column.

## Breaking changes

1. **`get_sessions(deserialize=False)` no longer returns runs.** Session dictionaries
   returned by the bulk listing API do not include a `runs` key (post-migration). Use
   `get_session(session_id)` or the new `get_runs(session_id=...)` to fetch runs. This is
   what makes session listing fast regardless of session size.

2. **Direct SQL against `agno_sessions.runs` breaks.** The column is dropped by the
   migration. Query the runs table instead, e.g.:

   ```sql
   SELECT run_data FROM ai.agno_runs WHERE session_id = :sid ORDER BY run_index;
   ```

3. **`Session.to_dict()` accepts `include_runs`.** Defaults to `True` (unchanged
   behavior). Adapters use `include_runs=False` internally to avoid serializing runs when
   writing the session row.

4. **Custom table names**: `PostgresDb`, `AsyncPostgresDb`, `SqliteDb` and
   `AsyncSqliteDb` accept a new `runs_table` argument (defaults to `"agno_runs"`).

Unchanged: `Agent`/`Team`/`Workflow` code, `session.get_messages()`,
`get_chat_history()`, AgentOS session endpoints, and `db.get_session()` all behave as
before — runs are reattached to sessions transparently on read.

## New APIs

The upgraded adapters expose direct run access (sync and async variants):

```python
# Get a single run
run = db.get_run(run_id="...")

# Get runs with filters and pagination
runs = db.get_runs(session_id="...", status=RunStatus.completed, limit=20)

# Get run rows without deserializing (returns (rows, total_count))
rows, total = db.get_runs(agent_id="...", deserialize=False)

# Delete runs
db.delete_run(run_id="...")
db.delete_runs(run_ids=["...", "..."])
```

## How writes work now (for the curious)

Sessions track which runs changed since the last save (`session.upsert_run()` marks the
run dirty). On `db.upsert_session(session)`:

1. The session row is upserted without any run data.
2. The run ids already stored for the session are fetched (cheap, indexed).
3. Only runs that are new or dirty are upserted into the runs table.

So a session with 500 runs writes exactly one run row when run 501 completes.

## Storage comparison

| Metric | v2.x (blob) | v3.0 (runs table) |
|--------|-------------|-------------------|
| Bytes written to store N runs | O(N²) | O(N) |
| Session row size | grows unbounded | small, constant |
| Fetch last N runs | load + parse all runs | indexed SQL query |
| Save a new run | rewrite all runs | single row INSERT |
