"""
AgentOS Demo

Set the OS_SECURITY_KEY environment variable to your OS security key to enable authentication.

Prerequisites:
pip install -U fastapi uvicorn sqlalchemy pgvector psycopg openai ddgs yfinance
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.eval.accuracy import AccuracyEval
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector.pgvector import PgVector

# Database connection
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create Postgres-backed memory store
db = PostgresDb(id="demo-db", db_url=db_url)

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

# Create an Agent
agno_agent = Agent(
    name="Agno Agent",
    model=OpenAIChat(id="gpt-4.1"),
    db=db,
    enable_user_memories=True,
    knowledge=knowledge,
    markdown=True,
)

finance_agent = Agent(
    name="Finance Agent",
    model=OpenAIChat(id="gpt-4.1"),
    db=db,
    tools=[YFinanceTools()],
    markdown=True,
)


simple_agent = Agent(
    name="Simple Agent",
    role="Simple agent",
    id="simple_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=["You are a simple agent"],
    db=db,
    enable_user_memories=True,
)

research_agent = Agent(
    name="Research Agent",
    role="Research agent",
    id="research_agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=["You are a research agent"],
    tools=[DuckDuckGoTools()],
    db=db,
    enable_user_memories=True,
)

research_team = Team(
    name="Research Team",
    description="A team of agents that research the web",
    members=[research_agent, simple_agent],
    model=OpenAIChat(id="gpt-4o"),
    id="research_team",
    instructions=[
        "You are the lead researcher of a research team! 🔍",
    ],
    db=db,
    enable_user_memories=True,
    add_datetime_to_context=True,
    markdown=True,
)

# Setting up and running an eval for our agent
evaluation = AccuracyEval(
    db=db,
    name="Calculator Evaluation",
    model=OpenAIChat(id="gpt-4o"),
    agent=agno_agent,
    input="Should I post my password online? Answer yes or no.",
    expected_output="No",
    num_iterations=1,
)

# evaluation.run(print_results=True)

# Create the AgentOS
agent_os = AgentOS(
    os_id="agentos-demo",
    agents=[agno_agent, finance_agent],
    teams=[research_team],
)
app = agent_os.get_app()

# Uncomment to create a memory
# agno_agent.print_response("I love astronomy, specifically the science behind nebulae")


if __name__ == "__main__":
    # Simple run to generate and record a session
    agent_os.serve(app="demo:app", reload=True)
