"""
Create/Update cultural knowledge after every interaction with your Agent.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo_2.db")

# Define the Agent
agent = Agent(
    model=Claude(id="claude-sonnet-4-5"), db=db, update_cultural_knowledge=True
)

# Run the agent
agent.print_response(
    "What would be the best way to cook vegetarian ramen? Please be detailed and provide a step by step guide."
)
