"""
AgentOS Default Database
========================

Pass a database to AgentOS once and every listed agent, team, or workflow that
does not define its own database inherits it. AgentOS provisions the database
tables during server startup when auto_provision_dbs is enabled.

Prerequisites: OPENAI_API_KEY is needed only for agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/02_databases/basic.py
Try: Open http://localhost:7777/config and compare the OS and agent db IDs
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

# ---------------------------------------------------------------------------
# Create Database and Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agent-os-default-db",
    db_file="tmp/databases.db",
)

# This agent intentionally omits db; AgentOS injects the default database.
database_agent = Agent(
    id="database-agent",
    name="Database Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer questions concisely.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="database-basics-os",
    description="AgentOS default-database inheritance with SQLite.",
    db=db,
    agents=[database_agent],
    auto_provision_dbs=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="basic:app", reload=True)
