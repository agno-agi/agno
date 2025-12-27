"""
AgentOS Demo

Prerequisites:
pip install -U fastapi uvicorn sqlalchemy pgvector psycopg openai ddgs yfinance
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.a2a import A2A
from agno.os.interfaces.agui import AGUI
from agno.os.interfaces.slack import Slack
from agno.os.interfaces.whatsapp import Whatsapp
from agno.team import Team
from agno.vectordb.pgvector import PgVector
from agno.workflow import Workflow
from agno.workflow.step import Step

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

# Create an agent
simple_agent = Agent(
    name="Simple Agent",
    role="Simple agent",
    id="simple-agent",
    model=OpenAIChat(id="gpt-5-mini"),
    instructions=["You are a simple agent"],
    knowledge=knowledge,
)


# Create a team
simple_team = Team(
    name="Simple Team",
    description="A team of agents",
    members=[simple_agent],
    model=OpenAIChat(id="gpt-5-mini"),
    id="simple-team",
    instructions=[
        "You are the team lead.",
    ],
    db=db,
    markdown=True,
)

# Create a workflow
simple_workflow = Workflow(
    name="Simple Workflow",
    description="A simple workflow",
    steps=[
        Step(agent=simple_team),
    ],
)

# Create an interface
slack_interface = Slack(agent=simple_team)
whatsapp_interface = Whatsapp(agent=simple_agent)
agui_interface = AGUI(agent=simple_agent)
a2a_interface = A2A(agents=[simple_agent])


# Create the AgentOS
agent_os = AgentOS(
    id="agentos-demo",
    agents=[simple_agent],
    teams=[simple_team],
    workflows=[simple_workflow],
    interfaces=[slack_interface, whatsapp_interface, agui_interface, a2a_interface],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="all_interfaces:app", port=7777)
