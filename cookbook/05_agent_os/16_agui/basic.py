"""
Serve an Agent over AG-UI
=========================

Mount one Agent on AgentOS's AG-UI interface and expose its response as an
AG-UI server-sent event stream.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/basic.py
Try: GET http://localhost:7777/status, then POST an AG-UI request to /agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create AG-UI AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-basic-db",
    db_file="tmp/agui_basic.db",
)

assistant = Agent(
    id="agui-assistant",
    name="AG-UI Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer clearly and concisely.",
)

agent_os = AgentOS(
    id="agui-basic-os",
    description="A minimal AgentOS with one AG-UI interface.",
    agents=[assistant],
    interfaces=[AGUI(agent=assistant)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AG-UI Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
