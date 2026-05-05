"""DDL statements used by the ClickHouse traces DB.

ClickHouse is an OLAP store — it is a great fit for trace ingestion (high write
throughput, columnar scans for aggregate queries) but a poor fit for sessions,
memories, or anything that needs row-level updates. The adapter only persists
the trace/span tables; everything else on ``BaseDb`` raises ``NotImplementedError``.

Engine choice:

* ``traces`` uses ``ReplacingMergeTree(version)`` so the same ``trace_id`` can
  be re-ingested as more spans arrive. ``version`` is a unix nanosecond
  timestamp; the latest write wins after a background merge. Reads use
  ``FINAL`` to materialize the merged row at query time.
* ``spans`` uses plain ``MergeTree`` — spans are immutable and append-only.

Partitioning is by month on ``start_time`` so retention can be enforced with a
single ``ALTER TABLE ... DROP PARTITION`` if desired.
"""

TRACES_DDL = """
CREATE TABLE IF NOT EXISTS {db}.{table} (
    trace_id        String,
    name            String,
    status          LowCardinality(String),
    start_time      DateTime64(6, 'UTC'),
    end_time        DateTime64(6, 'UTC'),
    duration_ms     Int64,
    run_id          Nullable(String),
    session_id      Nullable(String),
    user_id         Nullable(String),
    agent_id        Nullable(String),
    team_id         Nullable(String),
    workflow_id     Nullable(String),
    created_at      DateTime64(6, 'UTC'),
    version         UInt64 DEFAULT toUnixTimestamp64Nano(now64(6))
)
ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(start_time)
ORDER BY (start_time, trace_id)
"""


SPANS_DDL = """
CREATE TABLE IF NOT EXISTS {db}.{table} (
    span_id          String,
    trace_id         String,
    parent_span_id   Nullable(String),
    name             String,
    span_kind        LowCardinality(String),
    status_code      LowCardinality(String),
    status_message   Nullable(String),
    start_time       DateTime64(6, 'UTC'),
    end_time         DateTime64(6, 'UTC'),
    duration_ms      Int64,
    attributes       String,
    created_at       DateTime64(6, 'UTC')
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(start_time)
ORDER BY (trace_id, start_time, span_id)
"""


VERSIONS_DDL = """
CREATE TABLE IF NOT EXISTS {db}.{table} (
    table_name   String,
    version      String,
    created_at   DateTime64(6, 'UTC'),
    updated_at   Nullable(DateTime64(6, 'UTC')),
    _ver         UInt64 DEFAULT toUnixTimestamp64Nano(now64(6))
)
ENGINE = ReplacingMergeTree(_ver)
ORDER BY table_name
"""


TRACE_COLUMNS = (
    "trace_id",
    "name",
    "status",
    "start_time",
    "end_time",
    "duration_ms",
    "run_id",
    "session_id",
    "user_id",
    "agent_id",
    "team_id",
    "workflow_id",
    "created_at",
)


SPAN_COLUMNS = (
    "span_id",
    "trace_id",
    "parent_span_id",
    "name",
    "span_kind",
    "status_code",
    "status_message",
    "start_time",
    "end_time",
    "duration_ms",
    "attributes",
    "created_at",
)
