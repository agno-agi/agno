"""Async tracing into ClickHouse with AgentOS.

`AsyncClickhouseDb` mirrors `ClickhouseDb` but uses
`clickhouse_connect.get_async_client`. `setup_tracing` detects `AsyncBaseDb`
and `await`s the exporter calls automatically — no other wiring changes
versus the sync example.

As with the sync version, ClickHouse is **traces-only**. Sessions, memories,
and component configs live on a row-store; only traces flow into ClickHouse.

Requirements:
    uv pip install agno opentelemetry-api opentelemetry-sdk \\
        openinference-instrumentation-agno clickhouse-connect

Bring up local services:
    ./cookbook/scripts/run_clickhouse.sh   # ClickHouse on :8123 / :9000
    ./cookbook/scripts/run_pgvector.sh     # Postgres on :5532
"""

from agno.agent import Agent
from agno.db.clickhouse import AsyncClickhouseDb
from agno.db.postgres import AsyncPostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.hackernews import HackerNewsTools
from agno.tracing.setup import setup_tracing

# ---------------------------------------------------------------------------
# Databases
# ---------------------------------------------------------------------------

# Async row-store for sessions, memories, evals.
primary_db = AsyncPostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Async OLAP store dedicated to traces.
traces_db = AsyncClickhouseDb(
    host="localhost",
    port=8123,
    username="ai",
    password="ai",
    database="agno_traces",
)

# BatchSpanProcessor is essential for ClickHouse — it coalesces span exports
# into larger inserts, which the OLAP engine prefers.
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
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[HackerNewsTools()],
    instructions="You are a hacker news agent. Answer questions concisely.",
    markdown=True,
    db=primary_db,
)

agent_os = AgentOS(
    description="Async tracing example: Postgres for sessions, ClickHouse for traces",
    agents=[agent],
    db=traces_db,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="basic_agent_with_async_clickhousedb:app", reload=True)
