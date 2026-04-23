"""
Claude Agent SDK with session persistence.

Demonstrates multi-turn conversations where chat history is persisted
to Agno's DB. Each run is stored as a session with messages, so you
can resume conversations and see history in the AgentOS UI.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_session_agentos.py
"""

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb
from agno.os.app import AgentOS

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
pg_db = PostgresDb(db_url=db_url)

agent = ClaudeAgent(
    name="Claude Chat",
    model="claude-sonnet-4-20250514",
    allowed_tools=["WebSearch"],
    permission_mode="acceptEdits",
    max_turns=7,
    db=pg_db,
)

# ---------------------------------------------------------------------------
# Setup AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="claude-session-agentos",
    name="Claude Agent SDK Example",
    description="AgentOS serving a Claude Agent SDK agent",
    agents=[agent],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="claude_session_agentos:app", reload=True)
