"""
Postgres Database Backend
=========================

Use Postgres for production AgentOS persistence. The synchronous adapter is
the simplest default; select the asynchronous adapter when database work must
remain non-blocking in an async application.

Set AGENTOS_USE_ASYNC_POSTGRES=true to run the asynchronous variant.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_pgvector.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/postgres.py
Try: Open http://localhost:7777/config and inspect os_database
"""

from os import getenv

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Databases
# ---------------------------------------------------------------------------

sync_db = PostgresDb(
    id="agent-os-postgres-sync",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

async_db = AsyncPostgresDb(
    id="agent-os-postgres-async",
    db_url="postgresql+psycopg_async://ai:ai@localhost:5532/ai",
)

use_async = getenv("AGENTOS_USE_ASYNC_POSTGRES", "false").lower() == "true"
db = async_db if use_async else sync_db

# ---------------------------------------------------------------------------
# Create Agent and AgentOS
# ---------------------------------------------------------------------------

postgres_agent = Agent(
    id="postgres-agent",
    name="Postgres Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer questions concisely.",
    markdown=True,
)

agent_os = AgentOS(
    id="postgres-agent-os",
    description="AgentOS backed by sync or async Postgres.",
    db=db,
    agents=[postgres_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="postgres:app", reload=True)
