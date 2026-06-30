"""
Remote AgentOS Server for System Tests.

This server hosts the actual agents, teams, and workflows that the gateway
consumes via RemoteAgent, RemoteTeam, and RemoteWorkflow.
"""

import os

from agno.agent import Agent
from agno.db.postgres import AsyncPostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.middleware.jwt import JWTMiddleware
from agno.team.team import Team
from agno.tools.calculator import CalculatorTools
from agno.tools.websearch import WebSearchTools
from agno.vectordb.pgvector import PgVector
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

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
    id="remote-db",
    db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@postgres:5432/ai"),
)

# =============================================================================
# Knowledge Base Configuration
# =============================================================================

knowledge = Knowledge(
    name="Remote Knowledge",
    description="A knowledge base for the remote server",
    vector_db=PgVector(
        db_url=os.getenv("DATABASE_URL", "postgresql+psycopg://ai:ai@postgres:5432/ai"),
        table_name="remote_test_knowledge",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)

# =============================================================================
# Agent Configuration
# =============================================================================

# Agent 1: Assistant with calculator tools and memory
assistant = Agent(
    name="Assistant",
    id="assistant-agent",
    description="A helpful AI assistant with calculator capabilities.",
    model=OpenAIChat(id="gpt-5-mini"),
    db=db,
    instructions=[
        "You are a helpful AI assistant.",
        "Use the calculator tool for any math operations.",
        "You have access to a knowledge base - search it when asked about documents.",
    ],
    markdown=True,
    update_memory_on_run=True,
    tools=[CalculatorTools()],
    knowledge=knowledge,
    search_knowledge=True,
)

# Agent 2: Researcher with web search capabilities
researcher = Agent(
    name="Researcher",
    id="researcher-agent",
    description="A research assistant with web search capabilities.",
    model=OpenAIChat(id="gpt-5-mini"),
    update_memory_on_run=True,
    db=db,
    instructions=[
        "You are a research assistant.",
        "Search the web for information when needed.",
        "Provide well-researched, accurate responses.",
    ],
    markdown=True,
    tools=[WebSearchTools()],
)

# =============================================================================
# Team Configuration
# =============================================================================

research_team = Team(
    name="Research Team",
    id="research-team",
    description="A team that coordinates research and analysis tasks.",
    model=OpenAIChat(id="gpt-5-mini"),
    members=[assistant, researcher],
    instructions=[
        "You are a research team that coordinates multiple specialists.",
        "Delegate math questions to the Assistant.",
        "Delegate research questions to the Researcher.",
        "Combine insights from team members for comprehensive answers.",
    ],
    markdown=True,
    update_memory_on_run=True,
    db=db,
)

# =============================================================================
# Workflow Configuration
# =============================================================================

qa_workflow = Workflow(
    name="QA Workflow",
    description="A simple Q&A workflow that uses the assistant agent",
    id="qa-workflow",
    db=db,
    steps=[
        Step(
            name="Answer Question",
            agent=assistant,
        ),
    ],
)

# =============================================================================
# AgentOS Configuration
# =============================================================================

agent_os = AgentOS(
    id="remote-os",
    description="Remote AgentOS server hosting agents, teams, and workflows for system testing",
    agents=[assistant, researcher],
    teams=[research_team],
    workflows=[qa_workflow],
    knowledge=[knowledge],
    tracing=True,
    db=db,
)

# FastAPI app instance (for uvicorn)
app = agent_os.get_app()

app.add_middleware(
    JWTMiddleware,
    verification_keys=[JWT_SECRET_KEY],
    algorithm="HS256",
    authorization=ENABLE_AUTHORIZATION,
    verify_audience=False,
    # We have to exclude for the config endpoint to work correctly.
    excluded_route_paths=[
        "/health",
        "/config",
        "/agents",
        "/agents/*",
        "/teams",
        "/teams/*",
        "/workflows",
        "/workflows/*",
    ],
)

# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    reload = os.getenv("RELOAD", "true").lower() == "true"
    agent_os.serve(app="remote_server:app", reload=reload, host="0.0.0.0", port=7002, access_log=True)
