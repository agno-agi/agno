# ClickHouse Traces Database

`ClickhouseDb` and `AsyncClickhouseDb` are **traces-only** Agno DB adapters
backed by [ClickHouse](https://clickhouse.com/). They implement the trace/span
surface of `BaseDb` and intentionally leave session/memory/knowledge/eval
methods unimplemented — ClickHouse is an OLAP columnar store and is not a
good fit for those workloads.

## Why ClickHouse for traces?

Traces are the canonical OLAP workload: append-heavy ingest, fast scans across
billions of rows, time-bucketed aggregates, low cardinality on most filter
columns. OpenAI publicly migrated their tracing infrastructure to ClickHouse
for the same reason — if it scales for them, it scales for any agent
deployment built on Agno.

What ClickHouse is **not** good at:

- Row-level updates (no `UPDATE` in the OLTP sense; mutations are async, heavy)
- Multi-row transactions
- High-frequency single-row reads keyed by primary key

That's why this adapter pairs cleanly with a row-store. Use Postgres (or any
other Agno DB) for sessions, memories, knowledge content, and component
configs; use `ClickhouseDb` only for traces.

## Installation

```bash
pip install 'agno[clickhouse]'
# or, equivalently
pip install agno clickhouse-connect
```

You also need the OpenTelemetry packages used by `setup_tracing`:

```bash
pip install opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
```

## Running ClickHouse locally

The Agno cookbook ships a helper script:

```bash
./cookbook/scripts/run_clickhouse.sh
```

That brings up a single-node ClickHouse on `localhost:8123` (HTTP) and
`localhost:9000` (native), with `CLICKHOUSE_DB=ai`, `CLICKHOUSE_USER=ai`,
`CLICKHOUSE_PASSWORD=ai`. For production use the
[ClickHouse Cloud](https://clickhouse.cloud/) connection string works as-is
when you set `secure=True` and the appropriate `port`/`host`.

## Usage

### Basic (sync)

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.db.clickhouse import ClickhouseDb
from agno.models.openai import OpenAIResponses
from agno.tracing import setup_tracing

primary_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
traces_db = ClickhouseDb(
    host="localhost",
    port=8123,
    username="ai",
    password="ai",
    database="agno_traces",
)

setup_tracing(db=traces_db, batch_processing=True)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=primary_db,           # sessions, memories, etc.
    instructions="...",
)
agent.print_response("hello")
```

### Async

```python
from agno.db.clickhouse import AsyncClickhouseDb

traces_db = AsyncClickhouseDb(
    host="localhost", port=8123, username="ai", password="ai",
    database="agno_traces",
)
setup_tracing(db=traces_db, batch_processing=True)
```

`setup_tracing` detects `AsyncBaseDb` automatically and `await`s the
exporter calls.

### ClickHouse Cloud

```python
traces_db = ClickhouseDb(
    host="<your-host>.clickhouse.cloud",
    port=8443,
    username="default",
    password="<password>",
    database="agno_traces",
    secure=True,
)
```

### Re-using an existing client

If your application already has a `clickhouse_connect` client configured
(connection pooling, custom timeouts, etc.) inject it directly:

```python
import clickhouse_connect

client = clickhouse_connect.get_client(host="...", ...)
traces_db = ClickhouseDb(client=client, database="agno_traces")
```

## Schema

Two tables are created on first use:

### `agno_traces` — `ReplacingMergeTree(version)`

| column        | type                          | notes                              |
|---------------|-------------------------------|------------------------------------|
| `trace_id`    | `String`                      | part of the sort key               |
| `name`        | `String`                      | derived from the root span         |
| `status`      | `LowCardinality(String)`      | `OK` / `ERROR` / `UNSET`           |
| `start_time`  | `DateTime64(6, 'UTC')`        | partition key (`toYYYYMM`)         |
| `end_time`    | `DateTime64(6, 'UTC')`        |                                    |
| `duration_ms` | `Int64`                       |                                    |
| `run_id`      | `Nullable(String)`            |                                    |
| `session_id`  | `Nullable(String)`            |                                    |
| `user_id`     | `Nullable(String)`            |                                    |
| `agent_id`    | `Nullable(String)`            |                                    |
| `team_id`     | `Nullable(String)`            |                                    |
| `workflow_id` | `Nullable(String)`            |                                    |
| `created_at`  | `DateTime64(6, 'UTC')`        |                                    |
| `version`     | `UInt64`                      | server-defaulted insert sequence   |

`PARTITION BY toYYYYMM(start_time)` — drop a month with one
`ALTER TABLE ... DROP PARTITION` for retention.

`ORDER BY (start_time, trace_id)` — fast time-range scans.

`ReplacingMergeTree(version)` — re-ingesting the same `trace_id` (which
happens whenever a later span batch arrives) is safe; the latest `version`
wins after a background merge. Reads use `FINAL` for correctness.

### `agno_spans` — `MergeTree`

| column            | type                          | notes                              |
|-------------------|-------------------------------|------------------------------------|
| `span_id`         | `String`                      | part of the sort key               |
| `trace_id`        | `String`                      | part of the sort key               |
| `parent_span_id`  | `Nullable(String)`            |                                    |
| `name`            | `String`                      |                                    |
| `span_kind`       | `LowCardinality(String)`      |                                    |
| `status_code`     | `LowCardinality(String)`      |                                    |
| `status_message`  | `Nullable(String)`            |                                    |
| `start_time`      | `DateTime64(6, 'UTC')`        | partition key                      |
| `end_time`        | `DateTime64(6, 'UTC')`        |                                    |
| `duration_ms`     | `Int64`                       |                                    |
| `attributes`      | `String`                      | JSON-encoded                       |
| `created_at`      | `DateTime64(6, 'UTC')`        |                                    |

Spans are immutable, so a plain `MergeTree` is enough.

`attributes` is stored as JSON-in-`String` rather than the experimental
ClickHouse `JSON` column type, to avoid coupling the schema to a specific
server build. Query individual fields with `JSONExtractString(attributes,
'agno.run.id')` etc.

## How it integrates with `setup_tracing`

Agno's tracing pipeline:

```
Agent run  ->  OpenInference instrumentation  ->  OpenTelemetry SDK
            ->  BatchSpanProcessor (recommended)
            ->  DatabaseSpanExporter
            ->  ClickhouseDb.upsert_trace + create_spans
```

`DatabaseSpanExporter` (in `agno/tracing/exporter.py`) is provider-agnostic;
it groups spans by `trace_id`, builds a `Trace` aggregate, and calls
`upsert_trace` + `create_spans` on whichever DB it was given. ClickhouseDb
plugs in unchanged.

**Always enable batch processing for ClickHouse** (`batch_processing=True` on
`setup_tracing`). ClickHouse strongly prefers a smaller number of larger
inserts; the default `SimpleSpanProcessor` issues one insert per span and will
hit the server's `parts_to_throw_insert` limit under load. Reasonable
starting values:

```python
setup_tracing(
    db=traces_db,
    batch_processing=True,
    max_queue_size=2048,
    max_export_batch_size=512,
    schedule_delay_millis=5000,
)
```

## What works on this adapter

| Method                       | Status              |
|------------------------------|---------------------|
| `upsert_trace`               | implemented         |
| `get_trace`                  | implemented         |
| `get_traces` (paged + filter)| implemented         |
| `get_trace_stats`            | implemented         |
| `create_span` / `create_spans`| implemented        |
| `get_span` / `get_spans`     | implemented         |
| `table_exists`               | implemented         |
| schema-version               | implemented         |
| anything else                | `NotImplementedError` |

If you need session/memory persistence on the same instance, register a
second DB (e.g. `PostgresDb`) on the agent. Tracing flows through whichever
DB was passed to `setup_tracing`; agent state flows through `agent.db`.

## Operational notes

- **Retention:** `PARTITION BY toYYYYMM(start_time)` lets you expire old
  traces with a single `ALTER TABLE agno_traces DROP PARTITION '202602'`.
- **Mutations:** `ReplacingMergeTree` deduplicates on the sort key during
  background merges. Reads use `FINAL` so freshly-inserted duplicates are
  collapsed at query time. If query latency is critical, consider running
  `OPTIMIZE TABLE agno_traces FINAL` on a schedule.
- **Aggregations:** `total_spans` and `error_count` on a `Trace` are computed
  at read time from the spans table, mirroring the Postgres adapter. This
  avoids a write-time fan-out and lets the OLAP engine do what it's good at.
- **Cardinality:** trace/span tables can grow fast. Plan for it — ClickHouse
  is happy with billions of rows on a single node, but the cost shifts to
  storage. Use `LowCardinality(String)` for any new enum-like columns you
  add.
