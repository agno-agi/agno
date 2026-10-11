"""
Codex on AgentOS with session persistence.

Chat history is persisted to Agno's DB and the Codex thread id is stored on
the Agno session, so follow-up messages in the AgentOS UI resume the same
Codex thread.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_session_agentos.py
"""

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS

db = SqliteDb(db_file="tmp/codex_agentos.db")

agent = CodexAgent(
    name="Codex Chat",
    model="gpt-5.6-luna",
    sandbox="read-only",
    cwd=".",
    db=db,
)

# ---------------------------------------------------------------------------
# Setup AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="codex-session-agentos",
    name="Codex Example",
    description="AgentOS serving a Codex agent with persisted sessions",
    agents=[agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="codex_session_agentos:app", reload=True)
