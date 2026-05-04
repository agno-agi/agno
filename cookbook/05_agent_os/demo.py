"""
AgentOS Demo

Set JWT_VERIFICATION_KEY with your public key to enable RBAC.

Prerequisites:
uv pip install -U fastapi uvicorn sqlalchemy pgvector psycopg openai ddgs yfinance
"""

import os

from agno.agent import Agent
from agno.approval import approval
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.os.middleware import JWTMiddleware
from agno.team import Team
from agno.tools import tool
from agno.tools.mcp import MCPTools
from agno.tools.websearch import WebSearchTools
from agno.vectordb.pgvector import PgVector
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# Database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create Postgres-backed memory store
db = PostgresDb(db_url=db_url)

# Create Postgres-backed vector store
vector_db = PgVector(
    db_url=db_url,
    table_name="agno_docs",
)
knowledge = Knowledge(
    name="Agno Docs",
    contents_db=db,
    vector_db=vector_db,
)


@approval(type="required")
@tool(requires_confirmation=True)
def publish_demo_note(note: str) -> str:
    """Mock action that requires explicit approval before execution."""
    return "Approved note: " + note


# Create your agents
agno_agent = Agent(
    name="Agno Agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[
        MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp"),
        publish_demo_note,
    ],
    db=db,
    update_memory_on_run=True,
    knowledge=knowledge,
    markdown=True,
)

simple_agent = Agent(
    name="Simple Agent",
    role="Simple agent",
    id="simple_agent",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=["You are a simple agent"],
    db=db,
    update_memory_on_run=True,
)

research_agent = Agent(
    name="Research Agent",
    role="Research agent",
    id="research_agent",
    model=OpenAIChat(id="gpt-5.2"),
    instructions=["You are a research agent"],
    tools=[WebSearchTools()],
    db=db,
    update_memory_on_run=True,
)

# Create a team
research_team = Team(
    name="Research Team",
    description="A team of agents that research the web",
    members=[research_agent, simple_agent],
    model=OpenAIChat(id="gpt-4.1"),
    id="research_team",
    instructions=[
        "You are the lead researcher of a research team.",
    ],
    db=db,
    update_memory_on_run=True,
    add_datetime_to_context=True,
    markdown=True,
)

# Create a basic workflow
research_step = Step(
    name="Research Step",
    agent=research_agent,
)

draft_step = Step(
    name="Draft Step",
    agent=simple_agent,
)

content_creation_workflow = Workflow(
    name="content-creation-workflow",
    description="Basic two-step workflow for research and drafting",
    steps=[research_step, draft_step],
)


# # Public key used by AgentOS to verify JWT signatures
# JWT_VERIFICATION_KEY = os.getenv("JWT_VERIFICATION_KEY")
# if not JWT_VERIFICATION_KEY:
#     raise ValueError("JWT_VERIFICATION_KEY is required for demo RBAC setup")

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu3DP6ffAnZloIXUUzn20
RaFiCS2vMQ9C4gapYZIekS2HTuT6BwvWEqvhVsjPxY86BPqEgP6XUe1P5/E3qdU8
t3SfVYvLFovBjqyLkffhAlNBtTG9a4AMmBodo0gi1w2q5iLqYQJWpFOp2v1bkHdP
zDULtGiqCQVgpM9dwD8p6lOaxDkQ2+HGm/41LAkfIp9vJ+ounRiuWHvBa9N5O5ro
ItMpaEYmRYou8uJ8yEhOam/8g3EnAc4tFVde7PMeiy75I0+7BoOxgXQCIQ7TybqN
YCpylM0ojEp07eTA76PmeOB2U3yAQlx3FX3dYIYLcwoher5zjJWxbjCcIo2vCXsf
dwIDAQAB
-----END PUBLIC KEY-----"""
# Create the AgentOS
agent_os = AgentOS(
    id="agentos-demo",
    agents=[agno_agent],
    teams=[research_team],
    workflows=[content_creation_workflow],
    db=db,
    tracing=True,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[PUBLIC_KEY],
        algorithm="RS256",
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app="demo:app", port=7777, reload=True)
