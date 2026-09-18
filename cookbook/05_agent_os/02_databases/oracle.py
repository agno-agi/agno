"""
Oracle Database Backend
=======================

Use Oracle for AgentOS persistence. The synchronous adapter is the simplest
default; select the asynchronous adapter when database work must remain
non-blocking in an async application.

Set AGENTOS_USE_ASYNC_ORACLE=true to run the asynchronous variant.

Prerequisites: OPENAI_API_KEY and ./cookbook/scripts/run_oracle.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/oracle.py
Try: Open http://localhost:7777/config and inspect os_database
"""

from os import getenv

from agno.agent import Agent
from agno.db.oracle import AsyncOracleDb, OracleDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Databases
# ---------------------------------------------------------------------------

sync_db = OracleDb(
    id="agent-os-oracle-sync",
    db_url="oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1",
)

async_db = AsyncOracleDb(
    id="agent-os-oracle-async",
    db_url="oracle+oracledb_async://ai:ai@localhost:1521/?service_name=FREEPDB1",
)

use_async = getenv("AGENTOS_USE_ASYNC_ORACLE", "false").lower() == "true"
db = async_db if use_async else sync_db

# ---------------------------------------------------------------------------
# Create Agent and AgentOS
# ---------------------------------------------------------------------------

oracle_agent = Agent(
    id="oracle-agent",
    name="Oracle Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer questions concisely.",
    markdown=True,
)

agent_os = AgentOS(
    id="oracle-agent-os",
    description="AgentOS backed by sync or async Oracle.",
    db=db,
    agents=[oracle_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="oracle:app", reload=True)
