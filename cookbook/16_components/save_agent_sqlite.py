"""
This cookbook demonstrates how to save an agent to a SQLite database.
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

# agent.print_response("How many people live in Canada?")

# Save the agent to the database
version = agent.save()
print(f"Saved agent as version {version}")

# By default, saving an agent will create a new version of the agent

# Delete the agent from the database.
# This function will delete the Agent entity from the database.
# agent.delete()
