"""
Mount Multiple AG-UI Instances
==============================

Expose two agents from one AgentOS under independent AG-UI prefixes. Each
prefix receives its own POST /agui and GET /status routes.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/multiple_instances.py
Try: Compare POST /chat/agui with POST /analyst/agui on localhost:7777
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Agents and Interface Mounts
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-multiple-db",
    db_file="tmp/agui_multiple.db",
)

chat_agent = Agent(
    id="agui-chat-agent",
    name="AG-UI Chat Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer conversational questions in one or two sentences.",
)

analyst_agent = Agent(
    id="agui-analyst-agent",
    name="AG-UI Analyst Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    instructions="Answer with three labeled analytical points.",
)

agent_os = AgentOS(
    id="agui-multiple-os",
    description="Two independently addressable AG-UI interfaces.",
    agents=[chat_agent, analyst_agent],
    interfaces=[
        AGUI(agent=chat_agent, prefix="/chat"),
        AGUI(agent=analyst_agent, prefix="/analyst"),
    ],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Multi-Interface Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
