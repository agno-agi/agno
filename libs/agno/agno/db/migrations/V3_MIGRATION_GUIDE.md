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
- `MySQLDb` and `AsyncMySQLDb`
- `SingleStoreDb`
- `MongoDb` and `AsyncMongoDb` (uses a separate ``agno_runs`` collection)
- `FirestoreDb` (uses a separate ``agno_runs`` collection)
- `RedisDb` (uses ``<prefix>:runs:<run_id>`` keys plus a per-session sorted-set index)
- `ValkeyDb` (uses ``<prefix>:runs:<run_id>`` keys plus a per-session sorted-set index)
- `DynamoDb` (uses a separate ``agno_runs`` table with a ``session_id-created_at`` GSI)
- `SurrealDb` (uses a separate ``agno_runs`` table)
- `JsonDb` (uses a separate ``agno_runs.json`` file)
- `GcsJsonDb` (uses a separate ``agno_runs.json`` object in the bucket)

`InMemoryDb` and `ClickHouse` continue to store runs inline in the session. The
in-memory adapter does not benefit from the split (no I/O, no row-size limits),
and ClickHouse will be addressed in a follow-up release.

### MongoDB note

For MongoDB the v3.0 storage shape is a dedicated ``agno_runs`` collection with one
document per run, with the same fields as the SQL ``agno_runs`` table. The
``run_data`` field is a nested document (not flattened) to match the SQL design.
The legacy ``runs`` field on session documents is preserved by the migration; call
``db.cleanup_legacy_runs_field()`` (rather than ``cleanup_legacy_runs_column()``)
to unset it when you have verified the migration.

### Firestore note

Firestore's 1 MB document size limit is the *hard* version of MongoDB's 16 MB
limit — long sessions can simply fail to save in v2.x. v3.0 puts each run in its
own document in a dedicated ``agno_runs`` collection. The legacy ``runs`` field on
session documents is preserved by the migration; ``db.cleanup_legacy_runs_field()``
removes it once verified (uses Firestore ``DELETE_FIELD``).

### Redis note

Redis stores each run as a separate key (``<prefix>:runs:<run_id>``) and maintains
a per-session sorted set (``<prefix>:runs:by_session:<session_id>``) scored by
``run_index`` for cheap ordered reads. ``get_runs(session_id=...)`` is a
``ZRANGE`` + ``MGET`` round-trip rather than a full scan. The legacy ``runs``
field on the session record is preserved by the migration; call
``db.cleanup_legacy_runs_field()`` to drop it once verified.

### Valkey note

Valkey stores each run as a separate key (``<prefix>:runs:<run_id>``) and maintains
a per-session sorted set (``<prefix>:runs:by_session:<session_id>``) scored by
``run_index`` for cheap ordered reads. ``get_runs(session_id=...)`` is a ``ZRANGE``
plus one batched read of those keys rather than a full scan; the batch is issued
through the GLIDE client, which pipelines the whole page in a single round trip.
The legacy ``runs`` field on the session record is preserved by the migration;
call ``db.cleanup_legacy_runs_field()`` to drop it once verified.

### DynamoDB note

DynamoDB has a hard 400 KB per-item limit. The v2.x design — embedding the full
runs list in the session item — could simply fail to write for long sessions.
v3.0 puts each run in its own item in a dedicated ``agno_runs`` table with a
``session_id-created_at-index`` GSI for ordered reads. The legacy ``runs``
attribute on the session item is preserved by the migration; call
``db.cleanup_legacy_runs_field()`` to remove it once verified.

### SingleStore note

SingleStore requires every unique key to contain the shard-key columns, so the runs
table uses ``PRIMARY KEY (run_id, session_id)`` with ``SHARD KEY (session_id)``; a
single-column ``PRIMARY KEY (run_id)`` is rejected with ``ERROR 1744``, so no
deployment can have held the narrower key and there is nothing to migrate. The
consequence is that ``run_id`` alone is not unique here: the same ``run_id`` under two
``session_id``s leaves both rows in place, ``get_run`` returns one of them unordered,
``upsert_run`` inserts instead of updating, and ``delete_run`` removes every copy
across sessions. In normal use a ``run_id`` belongs to one session; the other SQL
backends keep ``PRIMARY KEY (run_id)``.

### SurrealDB note

SurrealDB stores each run in a dedicated ``agno_runs`` table with indexes on the
identity fields. The legacy ``runs`` field on session records is preserved by
the migration; call ``db.cleanup_legacy_runs_field()`` to drop it once verified.

### JSON / GCS-JSON note

The file-backed adapters keep runs in a sibling JSON file (``agno_runs.json``).
This brings API parity with the SQL/NoSQL adapters — same ``get_run`` /
``get_runs`` / ``delete_run`` surface — but it does **not** lift the underlying
I/O cost: every write still rewrites a single JSON file. These adapters are for
local development; for production workloads use one of the SQL or NoSQL
adapters. The legacy ``runs`` field is preserved by the migration and removed
via ``db.cleanup_legacy_runs_field()``.

## Migrating existing data

The migration is intentionally **non-destructive**. It creates the runs table and
copies every legacy run into it, but **leaves the legacy `runs` column on the sessions
table untouched** as a safety net. Writes never null that column either — it stays as
a frozen backup so that upgrading before running the migration can't lose history.
Once you have verified things, you drop the column manually (with `force=True`).

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

**This applies to session runs only.** Entity memory under `namespace="user"` does
not self-migrate and the explicit migration is required for it. See
[Entity memory: per-user keys](#entity-memory-per-user-keys) below.

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

**The entity memory re-key is not reversed by this.** `down()` refuses that step,
logs why, and reverts everything else. A database rolled back to v2.5.6 keeps its
entity memory rows on their v3.0 per-user keys, where a v2.x application will not
find them. Restore from a backup if you need those rows readable by v2.x.

## Entity memory: per-user keys

The same `v3.0.0` migration re-keys entity memory rows stored under
`namespace="user"`.

Before v3.0 the row key carried no user component, so two users who recorded an
entity with the same name and type shared one physical row: one user's facts
replaced the other's and then appeared in their reads and in the model's prompt
context. The migration moves each surviving row onto a key that embeds its owner.

```
before   entity_user_{entity_type}_{entity_id}
after    entity_user_{sha256(user_id)[:16]}_{entity_type}_{entity_id}
```

Only deployments that set `namespace="user"` on entity memory are affected, on the
backends that store learnings (`PostgresDb`, `SqliteDb` and `MongoDb` with their
async twins, and `ValkeyDb`). The default `namespace="global"` shares entities on
purpose and its keys do not change.

MongoDB is the exception to the quarantine below: its writes overwrite the owner
column, so a row two users wrote reads as self-consistent and is re-keyed onto the
last writer. A `quarantined` count of zero there means the evidence is unavailable,
not that no collision happened.

**This step is required.** Entity memory does not self-migrate. Until the re-key
runs, the store writes to the new per-user key while reads still match the old row,
so an entity that existed before the upgrade is split across two rows: reads return
the old one, listings show the entity twice, and a delete removes the row that reads
are not returning.

Run it from your deploy step, before the application serves traffic. Nothing does
that for you: inside AgentOS the manager is reachable only through the
`POST /databases/.../migrate` routes, which run with the app already up.

```python
import asyncio

from agno.db.migrations.manager import MigrationManager

asyncio.run(MigrationManager(db).up())
```

If a write does land first, the re-key folds the two rows back into one: the newer
row wins every conflict and the older only fills gaps.

### Rows that cannot be moved cleanly

A row whose stored content records a different user than its owner column held two
users' data before the fix, and the two are not separable. The migration moves these
under the `quarantined_user` namespace rather than deleting them: the content is
preserved and the entity store no longer reads it.

The learnings REST API filters on the owner column rather than the namespace, so a
quarantined row is still listed and mutable through `/learnings` by whichever user
the owner column names.

To delete them instead, and let entity memory re-capture from conversation. This
also deletes every row that has no owner:

```python
from agno.learn.migrations import rekey_user_entity_learnings

report = rekey_user_entity_learnings(db, dry_run=True)                        # inspect
report = rekey_user_entity_learnings(db, dry_run=False, purge_unrecoverable=True)
```

That helper is also how you re-run the re-key on its own. It does not consult the
schema version, so it works after the table has been stamped.

### Reading the report

`rekeyed` moved to the owner's key. `merged` folded into a row already on that key.
`quarantined` moved out of the store's reads. `keyed` was already correct.
`contaminated_keyed`, `unowned` and `malformed` are reported and left alone.
`conflicts` and `failed` need an operator: re-run the helper after resolving them.

`contaminated` lists the same rows as `quarantined`, or as `purged` when you passed
`purge_unrecoverable`, so do not add the two together.

## Eval runs: per-user isolation

The same `v3.0.0` migration adds an indexed `user_id` column to the eval runs table
(`agno_eval_runs` by default). It backs per-user isolation in AgentOS: with
`user_isolation` enabled a caller sees only their own eval runs; admins and unscoped
deployments see everything.

```
agno_eval_runs
├── run_id      TEXT PRIMARY KEY
├── ...
└── user_id     TEXT (indexed)   -- NULL for runs created before v3.0
```

Existing rows keep a `NULL` `user_id` — nothing is deleted or reassigned. An unowned
run stays visible to unscoped and admin callers and invisible to a scoped one. New
runs are stamped with their owner on write.

Only the seven SQL adapters (`PostgresDb`, `AsyncPostgresDb`, `SqliteDb`,
`AsyncSqliteDb`, `MySQLDb`, `AsyncMySQLDb`, `SingleStoreDb`) need schema work. The
rest store an eval run as a record and carry `user_id` with no schema change, so
`MigrationManager` logs `No version found for table agno_eval_runs` and moves on.
`ClickhouseDb` is traces-only and stores no eval runs.

It runs with the rest of the version — `MigrationManager(db).up()` — or on its own:

```python
asyncio.run(MigrationManager(db).up(table_type="evals"))
```

The column and index are added only when missing, so re-runs are safe; a table whose
adapter schema does not declare `user_id` is logged and skipped rather than failing
the run.

Reverting drops the index and then the column. Every row survives, but **the `user_id`
values are destroyed** — re-running `up()` restores the column with `NULL` everywhere,
not the previous owners. Back up first if the ownership data matters:

```python
asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="evals"))
```

SQLite reverts need SQLite 3.35+ for `ALTER TABLE ... DROP COLUMN`; on older builds
the revert logs and skips, matching `v2.5.6`'s behaviour.

## Components: unowned rows are shared

Components scope by `user_id` the same way, with one difference in what `NULL` means.
An eval run is a private record, so an unowned one is invisible to scoped callers; a
component is a building block other components reference, so an unowned one is
**shared** — `get_component` returns it to every scoped caller, the way unowned
knowledge content is readable by everyone. Without this, enabling `user_isolation` on
an existing deployment would 404 every pre-isolation component for every non-admin,
and team/workflow rehydration would silently drop shared members.

Writes stay strict: a scoped `upsert_component` or `delete_component` never touches a
row it does not own, and a scoped knowledge upsert whose content id collides with
another user's row (or a shared one) fails rather than replacing it and taking
ownership.

The consequence, deliberate and shared with knowledge, learnings and service accounts:
once `user_isolation` is on, a pre-isolation component or knowledge row (which has no
owner) is **read-only to every non-admin** — readable and runnable, but only an admin
(an unscoped caller) can edit or delete it. There is no backfill or claim step; a scoped
write to an unowned row is refused (`403` for knowledge, learnings and service accounts).
If those rows should belong to a user, stamp their `user_id` before enabling isolation.

## Metrics: per-user buckets

The same `v3.0.0` migration adds a `user_id` column to the metrics table
(`agno_metrics` by default), and does one thing no other table needs: it moves the
unique key onto that column.

```
agno_metrics
├── id                  TEXT PRIMARY KEY
├── date                DATE (indexed)
├── aggregation_period  TEXT             -- "daily"
├── user_id             TEXT NOT NULL    -- new in v3.0; "" = unowned
├── ...                                  -- run / session counts, token and model metrics
└── UNIQUE (user_id, date, aggregation_period)   -- was UNIQUE (date, aggregation_period)
```

v3.0 stores one metrics row per user per day instead of one row per day, so `user_id`
has to be part of the key. An un-migrated table is broken in two ways and neither is
loud. Without the column, `is_valid_table` rejects the table: Postgres and SQLite answer
`GET /metrics` with HTTP 500, MySQL answers HTTP 200 and an empty list, and SingleStore
raises the driver's `Unknown column 'user_id'` because SQLAlchemy cannot reflect its
JSON columns and an inspection failure counts as valid. With the column added by hand
but the legacy key still in place, Postgres and SQLite fail every recalculation — the
upsert names a conflict target that does not exist — while MySQL's
`ON DUPLICATE KEY UPDATE` matches the legacy key instead and files the second owner's
numbers on the first owner's row without erroring. What an operator notices either way
is that metrics stop moving, not that something failed.

It runs with the rest of the version — `MigrationManager(db).up()` — or on its own:

```python
asyncio.run(MigrationManager(db).up(table_type="metrics"))
```

Existing rows are stamped `""` rather than `NULL` — SQL treats every `NULL` as distinct,
which would silently break a unique key containing the column. `""` is the unowned
bucket, which is what pre-isolation history is, and the adapter maps it back to `None`
on the way out, so API consumers never see it. Rows are not split retroactively per
user: a metrics row does not record which sessions fed it.

One row is deleted as the column lands — the unowned `completed = false` row with the
newest date, and only when that date sits past every completed day. Such a row holds
the whole day's traffic for every user, and stamped unowned it would become a bucket
the per-user recalculation never rewrites, leaving that day counted once per user and
once again in the leftover row for good. Nothing is lost, because the recalculation is
certain to revisit that day and rebuild it from its sessions; the exception is a
deployment that prunes those sessions before migrating, so migrate first and prune
after. Every other unfinished row stays, owned or not — a deeper unfinished day may
have had its sessions pruned since, making its row the only record of that day, and a
stale-but-present row beats a deleted one. The delete only touches unowned rows and
only runs when the column or the key actually changed, so a re-run cannot remove
per-user buckets. Completed days are left exactly as they are.

Only the seven SQL adapters (`PostgresDb`, `AsyncPostgresDb`, `SqliteDb`,
`AsyncSqliteDb`, `MySQLDb`, `AsyncMySQLDb`, `SingleStoreDb`) need schema work — they
get the column, the key swap and the revert refusal. The other nine (`MongoDb`,
`FirestoreDb`, `DynamoDb`, `SurrealDb`, `RedisDb`, `ValkeyDb`, `JsonDb`, `GcsJsonDb`,
`InMemoryDb`) store a metrics record as a document and carry `user_id` with no schema
change, so the migration has nothing to do and reports as much. New records are written
per user from the first recalculation onwards.

SQLite rebuilds the table rather than altering it: it writes unique constraints into the
`CREATE TABLE` statement and has no `ALTER TABLE ... DROP CONSTRAINT`, so the migration
renames the table aside, creates the v3.0 shape from the adapter's schema, copies the
rows in and drops the old one — all in one transaction, so an interrupted run leaves the
original untouched. The new table comes from the schema, so a table carrying a column the
schema does not declare is refused and named in the log instead.

SingleStore keeps no unique constraint at all. A columnstore table may carry only one
`UNIQUE` index once any of them spans multiple columns, and the `id` primary key already
is one, so declaring the triple fails with error 1706 — which also means SingleStore
never had the legacy key and has nothing to swap. It gets the column and its index and
nothing else, and uniqueness on the triple lives in `bulk_upsert_metrics` instead, as a
select-then-write that is not atomic: two refreshes running at once can write the same
bucket twice, and the next recalculation collapses them.

MongoDB needs one thing more: its pre-v3.0 `date_1_aggregation_period_1` unique index
would reject every per-user document after the first for a date, so the collection's
index setup now drops it.

On Postgres and MySQL the column is added with a server `DEFAULT ''`, because
`ADD COLUMN ... NOT NULL` needs one on a populated table, and the migration drops that
default again once the existing rows are stamped. A migrated table therefore ends up
shaped like a freshly created one, and an `INSERT` that omits `user_id` is refused
rather than filed under the unowned bucket.

### Reverting metrics

Reverting runs on the seven SQL adapters only. The nine document backends had no schema
change to undo, so `down(table_type="metrics")` returns `False` there and leaves the
records as they are — per-user, which is not a shape v2.5.6 reads correctly. Consolidate
them with the application code, or drop the metrics collection and let v2.5.6 rebuild it
from its sessions.

On the SQL adapters the revert drops the column and puts the legacy key back, but **only
while every row is still unowned**. Once metrics have been collected per user, dropping
`user_id` would merge two owners' buckets for a date into duplicate rows that the legacy
key cannot even accept, so the revert refuses and logs instead:

```
Skipping revert of agno_metrics: it holds per-user metric rows, and dropping user_id
would merge them into duplicates for the same date. Consolidate or delete the owned
rows first.
```

Deleting the owned rows throws the per-user history away. To consolidate instead — one
row per date and period, carrying the summed numbers — run this first. It is written for
Postgres; the other SQL backends need the same shape with their own JSON functions.

```sql
BEGIN;

CREATE TEMP TABLE agno_metrics_merged AS
WITH tokens AS (
    SELECT date, aggregation_period, jsonb_object_agg(key, total) AS token_metrics
    FROM (
        SELECT m.date, m.aggregation_period, t.key, sum((t.value #>> '{}')::bigint) AS total
        FROM agno_metrics m, jsonb_each(m.token_metrics) t
        GROUP BY 1, 2, 3
    ) s
    GROUP BY 1, 2
), models AS (
    SELECT date, aggregation_period, jsonb_agg(jsonb_build_object(
               'model_id', model_id, 'model_provider', model_provider, 'count', total)) AS model_metrics
    FROM (
        SELECT m.date, m.aggregation_period,
               e ->> 'model_id' AS model_id, e ->> 'model_provider' AS model_provider,
               sum((e ->> 'count')::bigint) AS total
        FROM agno_metrics m, jsonb_array_elements(
                 CASE WHEN jsonb_typeof(m.model_metrics) = 'array' THEN m.model_metrics ELSE '[]'::jsonb END) e
        GROUP BY 1, 2, 3, 4
    ) s
    GROUP BY 1, 2
)
SELECT min(m.id) AS id, m.date, m.aggregation_period,
       sum(m.agent_runs_count)        AS agent_runs_count,
       sum(m.team_runs_count)         AS team_runs_count,
       sum(m.workflow_runs_count)     AS workflow_runs_count,
       sum(m.agent_sessions_count)    AS agent_sessions_count,
       sum(m.team_sessions_count)     AS team_sessions_count,
       sum(m.workflow_sessions_count) AS workflow_sessions_count,
       -- one owned bucket is one user; a pre-v3.0 row already counted the day's users
       greatest(count(*) FILTER (WHERE m.user_id IS DISTINCT FROM ''),
                max(m.users_count) FILTER (WHERE m.user_id = '')) AS users_count,
       coalesce(t.token_metrics, '{}'::jsonb) AS token_metrics,
       coalesce(md.model_metrics, '[]'::jsonb) AS model_metrics,
       min(m.created_at) AS created_at,
       max(m.updated_at) AS updated_at,
       bool_and(m.completed) AS completed
FROM agno_metrics m
LEFT JOIN tokens t ON t.date = m.date AND t.aggregation_period = m.aggregation_period
LEFT JOIN models md ON md.date = m.date AND md.aggregation_period = m.aggregation_period
GROUP BY m.date, m.aggregation_period, t.token_metrics, md.model_metrics;

DELETE FROM agno_metrics WHERE id NOT IN (SELECT id FROM agno_metrics_merged);

UPDATE agno_metrics m SET
    user_id = '',
    agent_runs_count        = g.agent_runs_count,
    team_runs_count         = g.team_runs_count,
    workflow_runs_count     = g.workflow_runs_count,
    agent_sessions_count    = g.agent_sessions_count,
    team_sessions_count     = g.team_sessions_count,
    workflow_sessions_count = g.workflow_sessions_count,
    users_count             = g.users_count,
    token_metrics           = g.token_metrics,
    model_metrics           = g.model_metrics,
    created_at              = g.created_at,
    updated_at              = g.updated_at,
    completed               = g.completed
FROM agno_metrics_merged g WHERE m.id = g.id;

DROP TABLE agno_metrics_merged;

COMMIT;
```

Qualify `agno_metrics` with your schema, or set `search_path`, if it is not on the
default one. The counts are summed, `token_metrics` is merged key by key, and
`model_metrics` — a JSON *array* of `{model_id, model_provider, count}` — is unnested,
grouped and re-aggregated so no model is listed twice. `users_count` becomes the number
of owned buckets for the day, which is what a v2.5.6 row meant by it; a row already
carrying a larger count is a pre-v3.0 one and keeps its own. Take a backup first: the
per-user breakdown is gone afterwards, and so is the `user_id` column once the revert
runs.

```python
asyncio.run(MigrationManager(db).down(target_version="2.5.6", table_type="metrics"))
```


## Breaking changes

1. **Direct SQL against `agno_sessions.runs`** stops being a complete view of session
   history once v3.0 is live — new runs go to the `agno_runs` table, not the legacy
   column. The legacy column is **never nulled by writes**; it stays as a frozen
   backup (holding whatever it held at upgrade time) until you explicitly run
   `cleanup_legacy_runs_column()`. Query the runs table instead:

   ```sql
   SELECT run_data FROM ai.agno_runs WHERE session_id = :sid ORDER BY run_index;
   ```

   Because writes no longer null the legacy column, `cleanup_legacy_runs_column()`
   (and `cleanup_legacy_runs_field()` on NoSQL/file adapters) will refuse to run
   while any session still holds a legacy blob — after you've run and verified the
   migration, pass `force=True` to reclaim the storage.

2. **`Session.to_dict()` accepts `include_runs`.** Defaults to `True` (unchanged
   behavior). Adapters use `include_runs=False` internally to avoid serializing
   runs when writing the session row.

3. **Custom table names**: `PostgresDb`, `AsyncPostgresDb`, `SqliteDb` and
   `AsyncSqliteDb` accept a new `runs_table` argument (defaults to `"agno_runs"`).

4. **Entity memory under `namespace="user"` is re-keyed**, and unlike session runs it
   does not self-migrate. Run the v3.0.0 migration before the application serves
   traffic, or an entity that existed before the upgrade is split across two rows
   until it does. Direct SQL against `agno_learnings` should expect
   `entity_user_{digest}_{type}_{id}` rather than `entity_user_{type}_{id}`, and a
   `quarantined_user` namespace holding rows that held two users' data. See
   [Entity memory: per-user keys](#entity-memory-per-user-keys). The re-key is not
   reversible.

5. **Culture feature removed**: The experimental culture feature has been removed
   entirely. This includes:
   - `from agno.culture import CultureManager` → `ModuleNotFoundError`
   - `Agent(culture_manager=..., enable_agentic_culture=..., update_cultural_knowledge=...)` → `TypeError`
   - `agent.get_culture_knowledge()` / `agent.aget_culture_knowledge()` → `AttributeError`
   - `db.upsert_cultural_knowledge()` and related DB methods → `AttributeError`
   - `db = PostgresDb(culture_table=...)` → `TypeError`

   Existing `agno_culture` database tables are orphaned (not dropped). Culture was
   marked "experimental" from introduction (Oct 2025).

Unchanged: `session.get_messages()`, `get_chat_history()`, AgentOS session endpoints,
and `db.get_session()` all behave as before — runs are reattached to sessions
transparently on read.

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
| v2.x → v3.0, no migration run yet | **Session runs:** reads merge runs table + legacy blob; new runs go to the table, the legacy blob is preserved so nothing is lost. **Entity memory under `namespace="user"`:** an entity that existed before the upgrade is split across two rows until the migration runs — reads return the pre-3.0 row and listings show the entity twice. Nothing is deleted, and the re-key folds the pair back together. |
| v2.x → v3.0, migration run, column not cleaned up | Reads go through the runs table, merged with the preserved legacy blob (deduped by `run_id`). Legacy column kept as a backup. |
| v2.x → v3.0, migration + `cleanup_legacy_runs_column()` | Final v3.0 state. Smallest sessions table. |
| Half-finished migration / hand-imported runs | Reads merge by `run_id`. No history is silently lost. |
