"""
Gateway AgentOS Server for System Tests.

This server acts as a gateway that consumes remote agents, teams, and workflows
defined in a separate remote server container.
"""

import os

from agno.agent import Agent, RemoteAgent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import RemoteTeam
from agno.vectordb.pgvector.pgvector import PgVector
from agno.workflow import RemoteWorkflow, Workflow
from agno.workflow.step import Step

# =============================================================================
# Database Configuration
# =============================================================================

db = PostgresDb(
    id="gateway-db",
    db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@postgres:5432/ai"),
)

knowledge = Knowledge(
    name="Gateway Knowledge",
    description="A knowledge base for the gateway server",
    vector_db=PgVector(
        db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@postgres:5432/ai"),
        table_name="system_test_knowledge",
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
    enable_user_memories=True,
    markdown=True,
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

# =============================================================================
# AgentOS Configuration
# =============================================================================

agent_os = AgentOS(
    id="gateway-os",
    description="Gateway AgentOS for system testing - consumes remote agents, teams, and workflows",
    agents=[
        local_agent,
        RemoteAgent(base_url=REMOTE_SERVER_URL, agent_id="assistant-agent"),
        RemoteAgent(base_url=REMOTE_SERVER_URL, agent_id="researcher-agent"),
    ],
    teams=[
        RemoteTeam(base_url=REMOTE_SERVER_URL, team_id="research-team"),
    ],
    workflows=[
        local_workflow,
        RemoteWorkflow(base_url=REMOTE_SERVER_URL, workflow_id="qa-workflow"),
    ],
    tracing=True,
    tracing_db=db,
)

# FastAPI app instance (for uvicorn)
app = agent_os.get_app()

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    reload = os.getenv("RELOAD", "true").lower() == "true"
    agent_os.serve(app="gateway_server:app", reload=reload, host="0.0.0.0", port=7001, access_log=True)
