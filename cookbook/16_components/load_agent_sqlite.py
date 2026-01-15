"""
This cookbook demonstrates how to load an agent from a SQLite database.

This is useful for loading a latest config of an Agent from the database.
"""

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat

# SQLite database - will be created if it doesn't exist
db = SqliteDb(db_file="tmp/agents.db")

agent = Agent(
    id="agno-agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    name="Agno Agent",
    db=db,
)

# Save the agent to the database first
agent.save()

# Load a specific version of the agent
agent.load(agent_id="agno-agent", db=db, version=1)

# Now use the agent
agent.print_response("How many people live in Canada?")
