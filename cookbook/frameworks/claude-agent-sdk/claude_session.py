"""
Claude Agent SDK with session persistence.

Demonstrates multi-turn conversations where chat history is persisted
to Agno's DB. Each run is stored as a session with messages, so you
can resume conversations and see history in the AgentOS UI.

Requirements:
    pip install claude-agent-sdk

Usage:
    python cookbook/frameworks/claude-agent-sdk/claude_session.py
"""

from agno.agents.claude import ClaudeAgent
from agno.db.postgres import PostgresDb

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

SESSION_ID = "demo-session-1"

# Turn 1
agent.print_response(
    "What are the latest developments in AI agents?",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 2 — same session
agent.print_response(
    "Which companies are leading in this space?",
    stream=True,
    session_id=SESSION_ID,
)

print(f"\n--- Session {SESSION_ID} persisted to Postgres ---")
