"""
Antigravity with session persistence.

Demonstrates a multi-turn conversation where the underlying Antigravity
environment (sandbox state, files, installed packages) is reused across
turns within the same session_id. Chat history is persisted to a local
SQLite DB so the conversation can be resumed.

Requirements:
    export GEMINI_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/antigravity/antigravity_session.py
"""

from agno.agents.antigravity import AntigravityAgent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="tmp/antigravity.db")

agent = AntigravityAgent(
    name="Antigravity Chat",
    db=db,
)

SESSION_ID = "antigravity-demo-1"

# Turn 1 — provision the sandbox and run something
agent.print_response(
    "Write a file called notes.txt containing the string 'hello agno'.",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 2 — same session: the env_id is reused, so notes.txt is still there
agent.print_response(
    "Read notes.txt back and tell me what it contains.",
    stream=True,
    session_id=SESSION_ID,
)

print(f"\n--- Session {SESSION_ID} persisted to tmp/antigravity.db ---")
