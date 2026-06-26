"""Traces with AgentOS, written to a dedicated ClickHouse traces database.

ClickHouse is a columnar OLAP store. It is a great fit for traces (high-volume
append, fast aggregate scans), but a poor fit for sessions/memories (no row-
level updates, no transactions). The recommended pattern is:

    Postgres (or another row-store)  ->  sessions + memories
    ClickHouse                       ->  traces only

`ClickhouseDb` only implements `BaseDb`'s trace/span surface; calling any
session, memory, or knowledge method on it will raise `NotImplementedError`.

Requirements:
    uv pip install agno opentelemetry-api opentelemetry-sdk \\
        openinference-instrumentation-agno clickhouse-connect

Bring up local services with:
    ./cookbook/scripts/run_clickhouse.sh   # ClickHouse on :8123 / :9000
    ./cookbook/scripts/run_pgvector.sh     # Postgres on :5532
"""

from agno.agent import Agent
from agno.db.clickhouse import ClickhouseDb
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.hackernews import HackerNewsTools
from agno.tracing.setup import setup_tracing

# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

# Row-store for sessions, memories, evals, etc.
primary_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# OLAP store dedicated to traces. Tables are created on first use.
traces_db = ClickhouseDb(
    host="localhost",
    port=8123,
    username="ai",
    password="ai",
    database="agno_traces",
)

# Wire the tracer to ClickHouse. BatchSpanProcessor amortizes inserts —
# critical for ClickHouse, which prefers larger batches over many tiny rows.
setup_tracing(
    db=traces_db,
    batch_processing=True,
    max_queue_size=2048,
    max_export_batch_size=512,
    schedule_delay_millis=5000,
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="HackerNews Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[HackerNewsTools()],
    instructions="You are a hacker news agent. Answer questions concisely.",
    markdown=True,
    db=primary_db,
)

agent_os = AgentOS(
    description="Tracing example: Postgres for sessions, ClickHouse for traces",
    agents=[agent],
    db=traces_db,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="basic_agent_with_clickhousedb:app", reload=True)
