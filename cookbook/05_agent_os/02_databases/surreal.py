"""
SurrealDB Database Backend
==========================

Configure SurrealDB with its client, URL, credentials, namespace, and database
instead of a SQL connection string. Local defaults match
./cookbook/scripts/run_surrealdb.sh.

Prerequisites: OPENAI_API_KEY, agno[surrealdb], and run_surrealdb.sh
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/surreal.py
Try: Open http://localhost:7777/config and inspect os_database
"""

from os import getenv

from agno.agent import Agent
from agno.db.surrealdb import SurrealDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SurrealDb(
    client=None,
    db_url=getenv("SURREALDB_URL", "ws://localhost:8000"),
    db_creds={
        "username": getenv("SURREALDB_USER", "root"),
        "password": getenv("SURREALDB_PASSWORD", "root"),
    },
    db_ns=getenv("SURREALDB_NAMESPACE", "agno"),
    db_db=getenv("SURREALDB_DATABASE", "agent_os"),
    id="agent-os-surreal",
)

# ---------------------------------------------------------------------------
# Create Agent and AgentOS
# ---------------------------------------------------------------------------

surreal_agent = Agent(
    id="surreal-agent",
    name="SurrealDB Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer questions concisely.",
    markdown=True,
)

agent_os = AgentOS(
    id="surreal-agent-os",
    description="AgentOS backed by SurrealDB.",
    db=db,
    agents=[surreal_agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="surreal:app", reload=True)
