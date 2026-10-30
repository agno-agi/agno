"""
Google ADK agent with session persistence.

Each Agno session is an ADK session with the same id. ADK keeps the native
conversation on its session service (in memory here); Agno stores every run in
its database, so the conversation also shows up in the AgentOS UI and is
replayed into a fresh ADK session when the process restarts.

Requirements:
    pip install google-adk
    export GOOGLE_API_KEY=...

Usage:
    .venvs/demo/bin/python cookbook/frameworks/google_adk/google_adk_session.py
"""

from agno.agents.google_adk import GoogleADKAgent
from agno.db.sqlite import SqliteDb
from google.adk.agents import LlmAgent

adk_agent = LlmAgent(
    name="chat",
    model="gemini-3.7-flash",
    instruction="You are a helpful assistant. Keep answers short.",
)

agent = GoogleADKAgent(
    name="ADK Chat",
    agent=adk_agent,
    db=SqliteDb(db_file="tmp/google_adk_sessions.db"),
)

SESSION_ID = "demo-session-1"

# Turn 1
agent.print_response(
    "My favourite planet is Neptune.", stream=True, session_id=SESSION_ID
)

# Turn 2: the same ADK session, so the model remembers the first turn
agent.print_response(
    "Which planet did I say I like?", stream=True, session_id=SESSION_ID
)

# Turn 3
agent.print_response(
    "Summarize what we discussed in one sentence.", stream=True, session_id=SESSION_ID
)

print("\n--- Session persisted to tmp/google_adk_sessions.db ---")
print(f"Session ID: {SESSION_ID}")
