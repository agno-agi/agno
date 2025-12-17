"""Example showing how to use AgentOS with Postgres as database"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.team.team import Team

# Setup the Postgres database
db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Agent Setup
agent = Agent(
    db=db,
    name="Basic Agent",
    id="basic-agent",
    model=OpenAIChat(id="gpt-4o"),
    add_history_to_context=True,
    num_history_runs=3,
)

# Team Setup
team = Team(
    db=db,
    id="basic-team",
    name="Team Agent",
    model=OpenAIChat(id="gpt-4o"),
    members=[agent],
    add_history_to_context=True,
    num_history_runs=3,
)

# AgentOS Setup
agent_os = AgentOS(
    description="Example OS setup",
    agents=[agent],
    teams=[team],
)

# Get the app
app = agent_os.get_app()

if __name__ == "__main__":
    # Serve the app
    agent_os.serve(app="postgres_demo:app", reload=True)
