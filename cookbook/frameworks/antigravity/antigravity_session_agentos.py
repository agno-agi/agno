"""
Antigravity on AgentOS with session persistence.

Serves an `AntigravityAgent` through AgentOS, backed by a SQLite DB so runs
and sessions persist across restarts and appear in the AgentOS UI's session
list.

Requirements:
    export GEMINI_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_session_agentos.py
"""

from agno.agents.antigravity import AntigravityAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

db = SqliteDb(db_file="tmp/antigravity_agentos.db")

antigravity_agent = AntigravityAgent(
    name="Antigravity",
    description="Antigravity with persisted sessions",
    db=db,
)

agent_os = AgentOS(
    name="Antigravity Sessioned",
    description="AgentOS serving an Antigravity-backed agent with SQLite sessions",
    agents=[antigravity_agent],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="antigravity_session_agentos:app", reload=True)
