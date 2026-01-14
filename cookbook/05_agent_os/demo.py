"""
AgentOS Demo

Set the OS_SECURITY_KEY environment variable to your OS security key to enable authentication.

Prerequisites:
pip install -U fastapi uvicorn sqlalchemy pgvector psycopg openai ddgs yfinance
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.mcp import MCPTools
from agno.vectordb.pgvector import PgVector

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

# Create your agents
agno_agent = Agent(
    name="Agno Agent",
    model=OpenAIChat(id="gpt-4.1"),
    tools=[MCPTools(transport="streamable-http", url="https://docs.agno.com/mcp")],
    db=db,
    enable_user_memories=True,
    knowledge=knowledge,
    markdown=True,
)

simple_agent = Agent(
    name="Simple Agent",
    role="Simple agent",
    id="simple_agent",
    model=OpenAIChat(id="gpt-5-mini"),
    instructions=["You are a simple agent"],
    db=db,
    enable_user_memories=True,
)

research_agent = Agent(
    name="Research Agent",
    role="Research agent",
    id="research_agent",
    model=OpenAIChat(id="gpt-5-mini"),
    instructions=["You are a research agent"],
    tools=[DuckDuckGoTools()],
    db=db,
    enable_user_memories=True,
)

# Create a team
research_team = Team(
    name="Research Team",
    description="A team of agents that research the web",
    members=[research_agent, simple_agent],
    model=OpenAIChat(id="gpt-4.1"),
    id="research_team",
    instructions=[
        "You are the lead researcher of a research team! 🔍",
    ],
    db=db,
    enable_user_memories=True,
    add_datetime_to_context=True,
    markdown=True,
)

# Create the AgentOS
agent_os = AgentOS(
    id="agentos-demo",
    agents=[agno_agent],
    teams=[research_team],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="demo:app", port=7777, reload=True)
