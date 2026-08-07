"""
Multi-turn conversations with OpenCode using Agno session management.

Each Agno session maps to a dedicated OpenCode server session, so the agent
keeps full context across turns. With a db configured, the mapping and the
conversation history are also persisted across restarts.

Requirements:
    npm install -g opencode-ai
    opencode serve --port 4096

Usage:
    .venvs/demo/bin/python cookbook/frameworks/opencode/opencode_session.py
"""

from agno.agents.opencode import OpenCodeAgent
from agno.db.sqlite import SqliteDb

agent = OpenCodeAgent(
    name="OpenCode Assistant",
    base_url="http://127.0.0.1:4096",
    db=SqliteDb(db_file="tmp/opencode_sessions.db"),
)

session_id = "opencode-demo-session"

# First turn: establish some context
agent.print_response(
    "My favorite programming language is Rust. Remember that.",
    session_id=session_id,
    stream=True,
)

# Second turn: the OpenCode session retains the context
agent.print_response(
    "What is my favorite programming language?",
    session_id=session_id,
    stream=True,
)
