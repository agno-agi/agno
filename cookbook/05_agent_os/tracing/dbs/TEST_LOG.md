# Test Log: tracing/dbs

> Tests not yet run. Run each file and update this log.

### basic_agent_with_mongodb.py

**Status:** PENDING

**Description:** Traces with AgentOS.

---

### basic_agent_with_postgresdb.py

**Status:** PENDING

**Description:** Traces with AgentOS.

---

### basic_agent_with_sqlite.py

**Status:** PENDING

**Description:** Traces with AgentOS using SqliteDb.

---

### basic_agent_with_clickhousedb.py

**Status:** PASS

**Description:** Postgres for sessions + ClickHouse as a dedicated OLAP traces
store. The `ClickhouseDb` traces backend was verified end-to-end against a live
ClickHouse (Docker, `./cookbook/scripts/run_clickhouse.sh`) with real agent runs
across all four modes (sync/async, streaming/non-streaming): traces and spans
persist, partial span batches reconcile into one logical trace per `trace_id`,
and `get_trace` / `get_traces` / `get_trace_stats` return the expected results.
The integration suite (`tests/integration/db/clickhouse`) also passes.

**Result:** Traces backend works as documented. The `serve()` app loop itself
was not launched (requires a running Postgres and an interactive server).

---
