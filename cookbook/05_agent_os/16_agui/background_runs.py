"""
Background Runs over AG-UI
==========================

Run an agent in the background through the AG-UI interface: the run survives
client disconnection, and a reconnecting client reattaches with a snapshot
replay followed by live events. No new endpoints — both behaviors ride the
existing POST /agui route via forwarded_props.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/background_runs.py

Start a background run (close the connection any time — the run continues):

    curl -N -X POST http://localhost:7777/agui \
      -H "Content-Type: application/json" \
      -d '{
        "thread_id": "demo-thread",
        "run_id": "demo-run-1",
        "messages": [{"id": "m1", "role": "user", "content": "Give me a detailed tour of the solar system."}],
        "tools": [],
        "context": [],
        "state": {},
        "forwarded_props": {"background": true}
      }'

Reattach after reconnecting (same thread_id/run_id, empty messages): the
server replies with RUN_STARTED, a MESSAGES_SNAPSHOT of everything missed,
then keeps streaming live events (or RUN_FINISHED if the run already ended):

    curl -N -X POST http://localhost:7777/agui \
      -H "Content-Type: application/json" \
      -d '{
        "thread_id": "demo-thread",
        "run_id": "demo-run-1",
        "messages": [],
        "tools": [],
        "context": [],
        "state": {},
        "forwarded_props": {"reattach": true}
      }'
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create AG-UI AgentOS
# ---------------------------------------------------------------------------

# Background execution persists run state, so a database is required
db = SqliteDb(
    id="agui-background-db",
    db_file="tmp/agui_background.db",
)

assistant = Agent(
    id="agui-background-assistant",
    name="AG-UI Background Assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
    instructions="Answer thoroughly and at length.",
)

agent_os = AgentOS(
    id="agui-background-os",
    description="AG-UI interface whose runs survive client disconnection.",
    agents=[assistant],
    interfaces=[AGUI(agent=assistant)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AG-UI Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
