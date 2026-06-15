# Agno v3.0 Storage Migration Guide: Normalized Runs Table

## Overview

Agno v3.0 changes how session runs are stored. Runs are no longer kept as a JSON
blob inside the sessions table — each run is now stored as its own row in a dedicated
runs table (`agno_runs` by default).

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
- Session rows stay small.
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

The migration is intentionally **non-destructive**. It creates the runs table and
copies every legacy run into it, but **leaves the legacy `runs` column on the sessions
table untouched** as a safety net. New writes will null that column as sessions are
touched, and once you have verified things, you drop the column manually.

### Step 1: Run the v3.0.0 migration

```python
import asyncio

from agno.db.migrations.manager import MigrationManager
from agno.db.postgres import PostgresDb

db = PostgresDb(db_url="postgresql+psycopg://...")

# Copies every run from agno_sessions.runs into agno_runs.
# Does NOT touch the legacy column.
asyncio.run(MigrationManager(db).up())
```

The migration is idempotent — re-runs use `ON CONFLICT DO NOTHING` and skip rows
that already exist. The legacy `runs` column is preserved so you can sanity-check
the migrated data against the original.

### Step 2 (optional, recommended): Lazy migration also works

You don't strictly *need* to run the migration before upgrading. v3.0 works against
an unmigrated database:

- **Reads** load runs from the runs table and **merge** them with anything still in
  the legacy `runs` column (by `run_id`). The runs table is the source of truth on
  conflicts; runs that only exist in the blob are still returned. This means you
  never lose history, even in partial-migration states.
- **The first save** of any session moves its remaining legacy runs into the runs
  table and clears the legacy column for that session.

This means active sessions self-migrate. The explicit migration is recommended for
dormant sessions and for reclaiming storage in bulk.

### Step 3: Drop the legacy column when you're ready

Once you have verified the migration and taken a backup, drop the legacy column to
reclaim the storage:

```python
db.cleanup_legacy_runs_column()
```

This refuses to drop the column if any session still has non-null legacy `runs`
content (a sign that that session was not migrated). If you really want to force
it anyway:

```python
db.cleanup_legacy_runs_column(force=True)
```

Async adapters expose the same helper as `await db.cleanup_legacy_runs_column()`.

### Reverting

To roll back to v2.5.6 (rebuilds the blobs from the runs table and drops the runs
table):

```python
asyncio.run(MigrationManager(db).down(target_version="2.5.6"))
```

## Breaking changes

1. **Direct SQL against `agno_sessions.runs`** will eventually break — the column
   stays put until you run `cleanup_legacy_runs_column()`, but new writes null it
   out as sessions are touched, so it stops being a complete view of session
   history once v3.0 is live. Query the runs table instead:

   ```sql
   SELECT run_data FROM ai.agno_runs WHERE session_id = :sid ORDER BY run_index;
   ```

2. **`Session.to_dict()` accepts `include_runs`.** Defaults to `True` (unchanged
   behavior). Adapters use `include_runs=False` internally to avoid serializing
   runs when writing the session row.

3. **Custom table names**: `PostgresDb`, `AsyncPostgresDb`, `SqliteDb` and
   `AsyncSqliteDb` accept a new `runs_table` argument (defaults to `"agno_runs"`).

Unchanged: `Agent`/`Team`/`Workflow` code, `session.get_messages()`,
`get_chat_history()`, AgentOS session endpoints, and `db.get_session()` all behave
as before — runs are reattached to sessions transparently on read.

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

# Drop the legacy `runs` column once everything is migrated
db.cleanup_legacy_runs_column()
```

## How writes work now (for the curious)

On `db.upsert_session(session)`:

1. The session row is upserted without any run data.
2. Every run on the in-memory session is upserted into the runs table (`ON CONFLICT
   DO UPDATE` on `run_id`).
3. If the sessions table still has a legacy `runs` column, that column is set to
   `NULL` for the session — so the runs table is the only source of truth going
   forward for that session.

So a session with 500 runs writes 500 run rows when you save (each one is small and
indexed, vs the old approach of one growing blob). For most workloads this is a
clear win over the v2.x O(N²) write amplification; if you have a hot path that
writes many times without changing runs, you can optimize further by skipping
sessions you didn't touch.

## Storage comparison

| Metric | v2.x (blob) | v3.0 (runs table) |
|--------|-------------|-------------------|
| Bytes written to store N runs | O(N²) | O(N) |
| Session row size | grows unbounded | small, constant |
| Fetch last N runs | load + parse all runs | indexed SQL query |
| Save a new run | rewrite all runs | per-session run upsert |

## Compatibility matrix

| Scenario | What you get |
|---|---|
| Fresh v3.0 install | No legacy column, runs in `agno_runs`. Just works. |
| v2.x → v3.0, no migration run yet | Reads merge runs table + legacy blob; first save per session moves runs over. |
| v2.x → v3.0, migration run, column not cleaned up | All reads go through the runs table. Legacy column sits empty as a backup. |
| v2.x → v3.0, migration + `cleanup_legacy_runs_column()` | Final v3.0 state. Smallest sessions table. |
| Half-finished migration / hand-imported runs | Reads merge by `run_id`. No history is silently lost. |
