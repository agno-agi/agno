"""
Stream Reasoning Events over AG-UI
==================================

Enable Agno's reasoning loop and translate its reasoning lifecycle into
AG-UI REASONING_START, content, and end events before the final answer.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/16_agui/reasoning_agent.py
Try: POST a multi-step logic problem to http://localhost:7777/reasoning/agui
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI

# ---------------------------------------------------------------------------
# Create Reasoning Agent
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="agui-reasoning-db",
    db_file="tmp/agui_reasoning.db",
)

reasoning_agent = Agent(
    id="agui-reasoning-agent",
    name="AG-UI Reasoning Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    reasoning=True,
    reasoning_min_steps=2,
    reasoning_max_steps=4,
    instructions="Solve the problem carefully, then give a concise final answer.",
)

agent_os = AgentOS(
    id="agui-reasoning-os",
    description="AgentOS translating Agno reasoning events to AG-UI.",
    agents=[reasoning_agent],
    interfaces=[AGUI(agent=reasoning_agent, prefix="/reasoning")],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Reasoning Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
