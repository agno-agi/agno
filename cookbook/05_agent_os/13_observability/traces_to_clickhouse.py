"""
Route AgentOS Traces to ClickHouse
==================================

Keep transactional sessions in SQLite while batching trace spans into a
dedicated ClickHouse OLAP store. AgentOS registers both databases, so trace
readback must select the tracing store with db_id=clickhouse-traces.

Prerequisites: OPENAI_API_KEY, clickhouse-connect, and local ClickHouse
Run: .venvs/demo/bin/python cookbook/05_agent_os/13_observability/traces_to_clickhouse.py
Try: Inspect GET /traces?db_id=clickhouse-traces after the printed live run
"""

import asyncio
import os

import httpx
from agno.agent import Agent
from agno.db.clickhouse import ClickhouseDb
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tracing import setup_tracing
from opentelemetry import trace as trace_api

# ---------------------------------------------------------------------------
# Create Split Trace Storage
# ---------------------------------------------------------------------------

AGENT_ID = "clickhouse-traced-agent"
PRIMARY_DB_ID = "clickhouse-primary"
TRACE_DB_ID = "clickhouse-traces"
SESSION_ID = "clickhouse-trace-session"

primary_db = SqliteDb(
    id=PRIMARY_DB_ID,
    db_file="tmp/observability_clickhouse_primary.db",
)

traces_db = ClickhouseDb(
    id=TRACE_DB_ID,
    host=os.getenv("CLICKHOUSE_HOST", "localhost"),
    port=int(os.getenv("CLICKHOUSE_PORT", "8123")),
    username=os.getenv("CLICKHOUSE_USER", "ai"),
    password=os.getenv("CLICKHOUSE_PASSWORD", "ai"),
    database=os.getenv("CLICKHOUSE_DATABASE", "agno_traces"),
)

# Manual setup exposes batching controls for an append-oriented trace store.
# When no custom batching is needed, AgentOS(tracing=True, db=traces_db) selects
# the same destination automatically.
setup_tracing(
    db=traces_db,
    batch_processing=True,
    max_queue_size=2048,
    max_export_batch_size=512,
    schedule_delay_millis=1000,
)

clickhouse_agent = Agent(
    id=AGENT_ID,
    name="ClickHouse Traced Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=primary_db,
    instructions="Reply in one short sentence.",
)

agent_os = AgentOS(
    id="clickhouse-tracing-os",
    description="SQLite sessions with traces routed to ClickHouse.",
    db=traces_db,
    agents=[clickhouse_agent],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Split Trace Demo
# ---------------------------------------------------------------------------


async def run_clickhouse_demo() -> None:
    """Generate a trace, flush it, and read it from the selected trace DB."""
    run_output = await clickhouse_agent.arun(
        "Explain why traces suit an append-oriented store in one sentence.",
        session_id=SESSION_ID,
        user_id="observability-user",
    )

    tracer_provider = trace_api.get_tracer_provider()
    force_flush = getattr(tracer_provider, "force_flush", None)
    if not callable(force_flush) or not force_flush():
        raise RuntimeError("The tracing provider did not flush its ClickHouse batch")

    if primary_db.get_session(SESSION_ID) is None:
        raise RuntimeError("The transactional session was not stored in SQLite")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://agent-os",
    ) as client:
        ambiguous_response = await client.get(
            "/traces",
            params={"agent_id": AGENT_ID},
        )
        if ambiguous_response.status_code != 400:
            raise RuntimeError("Split storage should require the db_id query parameter")

        trace_response = await client.get(
            "/traces",
            params={"agent_id": AGENT_ID, "db_id": TRACE_DB_ID, "limit": 20},
        )
        trace_response.raise_for_status()
        trace_page = trace_response.json()

        matching_traces = [
            trace
            for trace in trace_page["data"]
            if trace["run_id"] == run_output.run_id
        ]
        if len(matching_traces) != 1:
            raise RuntimeError("ClickHouse readback did not find the new run trace")

        trace_id = matching_traces[0]["trace_id"]
        detail_response = await client.get(
            f"/traces/{trace_id}",
            params={"db_id": TRACE_DB_ID},
        )
        detail_response.raise_for_status()
        trace_detail = detail_response.json()
        if not trace_detail["tree"]:
            raise RuntimeError("ClickHouse trace detail has no span tree")

    print(f"Session store: {PRIMARY_DB_ID} ({SESSION_ID})")
    print(f"Trace store: {TRACE_DB_ID}")
    print(f"Run ID: {run_output.run_id}")
    print(
        f"Trace ID: {trace_id} "
        f"({trace_detail['total_spans']} span(s), {trace_detail['status']})"
    )
    print(f"GET /traces without db_id: {ambiguous_response.status_code}")


if __name__ == "__main__":
    asyncio.run(run_clickhouse_demo())
