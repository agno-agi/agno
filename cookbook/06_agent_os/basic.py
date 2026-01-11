"""Minimal example for AgentOS."""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS

# Setup the database
db = PostgresDb(id="basic-db", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Setup basic agents, teams and workflows
agent = Agent(
    name="Basic Agent",
    instructions=["You are a basic agent that can answer questions and perform tasks."],
    markdown=True,
    db=db,  # Pass the db instance here
    add_history_to_context=True,
    add_session_state_to_context=True,
    add_datetime_to_context=True,
    tools=[],
    reasoning=True,
    reasoning_max_steps=4,
    debug_mode=True,
)

# Setup our AgentOS app
agent_os = AgentOS(description="Example app for basic agent", agents=[agent])
app = agent_os.get_app()


if __name__ == "__main__":
    """Run your AgentOS.

    You can see the configuration and available apps at:
    http://localhost:7777/config

    """
    agent_os.serve(app="basic:app", reload=True)
