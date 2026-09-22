# Observability

AgentOS turns execution telemetry into an operational API: traces reveal the
span-by-span path through runs, while metrics aggregate persisted activity by
day. This lesson closes both loops by generating data and reading it back
through the same routes used by monitoring clients.

## Files

| File | What it teaches |
|---|---|
| `basic.py` | Enable tracing with `tracing=True` and discover the trace routes. |
| `read_traces.py` | Run sync and async agents, fetch their traces, and print the nested span trees. |
| `filtering.py` | Build a `FilterExpr`, inspect the filter schema, and execute an advanced trace search. |
| `traces_to_clickhouse.py` | Split transactional sessions from a batched ClickHouse trace store and select it with `db_id`. |
| `metrics.py` | Refresh daily metrics from persisted sessions and read the aggregate back. |
| `os_metrics.py` | Serve agents on two models and read their model usage from `GET /os/metrics`. |

## Prerequisites

Set `OPENAI_API_KEY` for the live agent runs. The demo environment also needs
the OpenTelemetry packages used by Agno tracing:

```bash
uv pip install --python .venvs/demo/bin/python \
  opentelemetry-api opentelemetry-sdk openinference-instrumentation-agno
```

The ClickHouse example additionally needs the Python driver and a local
server:

```bash
uv pip install --python .venvs/demo/bin/python clickhouse-connect
./cookbook/scripts/run_clickhouse.sh
```

The helper exposes ClickHouse on port `8123` with user `ai`, password `ai`.
Override `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER`,
`CLICKHOUSE_PASSWORD`, or `CLICKHOUSE_DATABASE` when your service differs.

## Run the examples

Start the smallest traced AgentOS:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/13_observability/basic.py
```

After calling its served agent, inspect `GET /traces`,
`GET /traces/{trace_id}`, `POST /traces/search`, and
`GET /traces/filter-schema`. The same `tracing=True` switch instruments local
agents, teams, and workflows registered with that OS.

Serve two agents on different models to read model usage:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/13_observability/os_metrics.py
```

After running both agents, open `GET /os/metrics` for the model usage
breakdown of the last 30 days, or narrow it with
`?starting_date=YYYY-MM-DD&ending_date=YYYY-MM-DD`. `GET /os/metrics/sessions`
counts the sessions created per day and compares the window with the one of
the same length before it. Both are built from the daily metrics, so to include
runs made after the first read, call `POST /metrics/refresh` and pass
`refresh=true`.

The other files generate and inspect their own data in one process:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/13_observability/read_traces.py
.venvs/demo/bin/python cookbook/05_agent_os/13_observability/filtering.py
.venvs/demo/bin/python cookbook/05_agent_os/13_observability/metrics.py
.venvs/demo/bin/python cookbook/05_agent_os/13_observability/traces_to_clickhouse.py
```

## Dedicated trace storage

`traces_to_clickhouse.py` keeps mutable session state in SQLite and sends only
trace and span writes to ClickHouse. It calls `setup_tracing()` directly to
configure batch export; `AgentOS(tracing=True)` is the simpler path when the
default exporter settings are sufficient.

Because the split-store OS registers both database IDs, requests to
`GET /traces` are ambiguous until the client passes
`db_id=clickhouse-traces`. ClickHouse is intentionally a traces-only adapter;
use a transactional row store for sessions, memories, knowledge, evals, and
component configuration.
