"""
Serve one AgentOS gateway over local and remote components
==========================================================

The gateway registers a local Agent alongside native AgentOS, Agno A2A REST,
and Google ADK JSON-RPC components. Callers use one AgentOS API on port 7777
without needing to know which transport backs each entity.

Prerequisites: start all three files under `servers/`; set OPENAI_API_KEY and GOOGLE_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/05_gateway.py
Try: fetch GET http://127.0.0.1:7777/config, then run any listed entity
"""

from agno.agent import Agent, RemoteAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import RemoteTeam
from agno.workflow import RemoteWorkflow

# ---------------------------------------------------------------------------
# Create Local Component
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="remote-gateway-db",
    db_file="tmp/remote_gateway.db",
)

gateway_agent = Agent(
    id="gateway-agent",
    name="Gateway Agent",
    description="A local Agent registered beside remote components.",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Answer briefly and identify yourself as the local gateway Agent.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Remote Components
# ---------------------------------------------------------------------------

remote_agentos_agent = RemoteAgent(
    base_url="http://127.0.0.1:7780",
    agent_id="assistant-agent",
)

remote_a2a_agent = RemoteAgent(
    base_url="http://127.0.0.1:7781/a2a/agents/a2a-assistant",
    agent_id="a2a-assistant",
    protocol="a2a",
    a2a_protocol="rest",
)

remote_adk_agent = RemoteAgent(
    base_url="http://127.0.0.1:8001",
    agent_id="facts_agent",
    protocol="a2a",
    a2a_protocol="json-rpc",
)

remote_team = RemoteTeam(
    base_url="http://127.0.0.1:7780",
    team_id="research-team",
)

remote_workflow = RemoteWorkflow(
    base_url="http://127.0.0.1:7780",
    workflow_id="qa-workflow",
)

# ---------------------------------------------------------------------------
# Create Gateway AgentOS
# ---------------------------------------------------------------------------

agent_os = AgentOS(
    id="remote-gateway-os",
    name="Remote Gateway",
    description="One AgentOS surface over local, AgentOS, and A2A components.",
    db=db,
    agents=[
        gateway_agent,
        remote_agentos_agent,
        remote_a2a_agent,
        remote_adk_agent,
    ],
    teams=[remote_team],
    workflows=[remote_workflow],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run Gateway AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, host="127.0.0.1", port=7777)
