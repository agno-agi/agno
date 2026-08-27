"""
Serve an Agno Agent through the A2A REST interface
==================================================

This server is the first-party A2A peer used by RemoteAgent. AgentOS retains
its normal health and config routes while exposing the Agent under `/a2a`.

Prerequisites: OPENAI_API_KEY and the `agno[a2a]` extra
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/servers/a2a_server.py
Try: fetch GET http://127.0.0.1:7781/a2a/agents/a2a-assistant/.well-known/agent-card.json
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools.calculator import CalculatorTools

# ---------------------------------------------------------------------------
# Create Database
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="remote-a2a-db",
    db_file="tmp/remote_a2a.db",
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

a2a_assistant = Agent(
    id="a2a-assistant",
    name="A2A Assistant",
    description="An Agno Agent served through the standard A2A REST surface.",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "Answer requests received over A2A.",
        "Use the calculator for arithmetic.",
        "Keep responses concise.",
    ],
    tools=[CalculatorTools()],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="remote-a2a-os",
    name="Remote A2A Server",
    description="Agno A2A backend for RemoteAgent examples.",
    db=db,
    agents=[a2a_assistant],
    a2a_interface=True,
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7781)
