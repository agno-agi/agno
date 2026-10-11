"""
Codex with session persistence.

Demonstrates multi-turn conversations where chat history is persisted
to Agno's DB. The Codex thread id is stored on the Agno session, so the
second turn resumes the same Codex thread and keeps its full context.

Requirements:
    pip install openai-codex

Usage:
    .venvs/demo/bin/python cookbook/frameworks/codex/codex_session.py
"""

from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb

db = SqliteDb(db_file="tmp/codex_sessions.db")

agent = CodexAgent(
    name="Codex Chat",
    model="gpt-5.6-luna",
    sandbox="read-only",
    db=db,
)

SESSION_ID = "codex-demo-session-1"

# Turn 1
agent.print_response(
    "My favourite programming language is Rust. Reply with one sentence acknowledging that.",
    stream=True,
    session_id=SESSION_ID,
)

# Turn 2 -- same session, same Codex thread
agent.print_response(
    "What is my favourite programming language? Answer in one word.",
    stream=True,
    session_id=SESSION_ID,
)

print(f"\n--- Session {SESSION_ID} persisted to SQLite ---")
