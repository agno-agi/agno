"""
Gateway AgentOS Server for System Tests.

This server acts as a gateway that consumes remote agents, teams, and workflows
defined in a separate remote server container.
"""

import os

from agno.agent import Agent, RemoteAgent
from agno.db.postgres import AsyncPostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.interfaces.a2a import A2A
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.slack import Slack
from agno.team import RemoteTeam, Team
from agno.vectordb.pgvector.pgvector import PgVector
from agno.workflow import RemoteWorkflow, Workflow
from agno.workflow.step import Step

# =============================================================================
# JWT Authorization Configuration
# =============================================================================

# Shared secret key for JWT verification (in production, use proper key management)
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "test-secret-key-for-system-tests-do-not-use-in-production")
ENABLE_AUTHORIZATION = os.getenv("ENABLE_AUTHORIZATION", "true").lower() == "true"

# =============================================================================
# Database Configuration
# =============================================================================

db = AsyncPostgresDb(
    id="gateway-db",
    db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@postgres:5432/ai"),
)

knowledge = Knowledge(
    name="Gateway Knowledge",
    description="A knowledge base for the gateway server",
    vector_db=PgVector(
        db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@postgres:5432/ai"),
        table_name="gateway_knowledge",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)
# =============================================================================
# Local Agent for Gateway
# =============================================================================

local_agent = Agent(
    name="Gateway Agent",
    id="gateway-agent",
    description="A local agent on the gateway for testing",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    knowledge=knowledge,
    instructions=["You are a helpful assistant on the gateway server."],
    update_memory_on_run=True,
    markdown=True,
)

# =============================================================================
# Local Team for Gateway
# =============================================================================

local_team = Team(
    name="Gateway Team",
    id="gateway-team",
    description="A local team on the gateway for testing",
    model=OpenAIChat(id="gpt-4o-mini"),
    members=[local_agent],
    db=db,
)

# =============================================================================
# Local Workflow for Gateway
# =============================================================================

local_workflow = Workflow(
    name="Gateway Workflow",
    description="A local workflow on the gateway for testing",
    id="gateway-workflow",
    db=db,
    steps=[
        Step(
            name="Gateway Step",
            agent=local_agent,
        ),
    ],
)

# =============================================================================
# Remote Configuration
# =============================================================================

REMOTE_SERVER_URL = os.getenv("REMOTE_SERVER_URL", "http://remote-server:7002")
ADK_SERVER_URL = os.getenv("ADK_SERVER_URL", "http://adk-server:7003")
REMOTE_A2A_SERVER_URL = os.getenv("REMOTE_A2A_SERVER_URL", "http://agno-a2a-server:7004")

# Remote agent for interface testing
remote_assistant = RemoteAgent(base_url=REMOTE_SERVER_URL, agent_id="assistant-agent")
remote_researcher = RemoteAgent(base_url=REMOTE_SERVER_URL, agent_id="researcher-agent")

# Remote team for interface testing
remote_team = RemoteTeam(base_url=REMOTE_SERVER_URL, team_id="research-team")

# Remote workflow for interface testing
remote_workflow = RemoteWorkflow(base_url=REMOTE_SERVER_URL, workflow_id="qa-workflow")

# ADK Remote agent (A2A protocol)
adk_facts_agent = RemoteAgent(
    base_url=ADK_SERVER_URL,
    agent_id="facts_agent",
    protocol="a2a",
    a2a_protocol="json-rpc",  # Needed for Google ADK servers
)

remote_a2a_assistant = RemoteAgent(
    base_url=REMOTE_A2A_SERVER_URL + "/a2a/agents/assistant-agent-2",  # Agno's format for a2a endpoints
    agent_id="assistant-agent-2",
    protocol="a2a",
)

remote_a2a_researcher = RemoteAgent(
    base_url=REMOTE_A2A_SERVER_URL + "/a2a/agents/researcher-agent-2",  # Agno's format for a2a endpoints
    agent_id="researcher-agent-2",
    protocol="a2a",
)

# A2A Remote team and workflow
remote_a2a_team = RemoteTeam(
    base_url=REMOTE_A2A_SERVER_URL + "/a2a/teams/research-team-2",
    team_id="research-team-2",
    protocol="a2a",
)

remote_a2a_workflow = RemoteWorkflow(
    base_url=REMOTE_A2A_SERVER_URL + "/a2a/workflows/qa-workflow-2",
    workflow_id="qa-workflow-2",
    protocol="a2a",
)

# =============================================================================
# Interface Configuration
# =============================================================================

# AG-UI Interfaces (for local agent, remote agent, and team)
agui_local = AGUI(agent=local_agent, prefix="/agui/local", tags=["AGUI-Local"])
agui_remote = AGUI(agent=remote_assistant, prefix="/agui/remote", tags=["AGUI-Remote"])
agui_team = AGUI(team=remote_team, prefix="/agui/team", tags=["AGUI-Team"])

# Slack Interfaces (for local agent, remote agent, team, and workflow)
slack_local = Slack(agent=local_agent, prefix="/slack/local", tags=["Slack-Local"])
slack_remote = Slack(agent=remote_assistant, prefix="/slack/remote", tags=["Slack-Remote"])
slack_team = Slack(team=remote_team, prefix="/slack/team", tags=["Slack-Team"])
slack_workflow = Slack(workflow=local_workflow, prefix="/slack/workflow", tags=["Slack-Workflow"])

# A2A Interface (exposes all agents, teams, and workflows)
a2a_interface = A2A(
    agents=[local_agent, remote_assistant, remote_researcher],
    teams=[remote_team],
    workflows=[local_workflow, remote_workflow],
    prefix="/a2a",
    tags=["A2A"],
)

# =============================================================================
# AgentOS Configuration
# =============================================================================


agent_os = AgentOS(
    id="gateway-os",
    description="Gateway AgentOS for system testing - consumes remote agents, teams, and workflows",
    agents=[
        local_agent,
        remote_assistant,
        remote_researcher,
        adk_facts_agent,
        remote_a2a_assistant,
        remote_a2a_researcher,
    ],
    teams=[
        local_team,
        remote_team,
        remote_a2a_team,
    ],
    workflows=[
        local_workflow,
        remote_workflow,
        remote_a2a_workflow,
    ],
    interfaces=[
        agui_local,
        agui_remote,
        agui_team,
        slack_local,
        slack_remote,
        slack_team,
        slack_workflow,
        a2a_interface,
    ],
    tracing=True,
    db=db,
    enable_mcp_server=True,
    authorization=ENABLE_AUTHORIZATION,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET_KEY],
        algorithm="HS256",
    )
    if ENABLE_AUTHORIZATION
    else None,
)

# FastAPI app instance (for uvicorn)
app = agent_os.get_app()

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    reload = os.getenv("RELOAD", "true").lower() == "true"
    agent_os.serve(app="gateway_server:app", reload=reload, host="0.0.0.0", port=7001, access_log=True)
