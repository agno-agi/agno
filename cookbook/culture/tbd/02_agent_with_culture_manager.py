"""
Create or update cultural knowledge after every interaction with your Agent. The Culture Manager will be called after every interaction to create or update cultural knowledge.
Based on the interaction, the Culture Manager will decide to add or update cultural knowledge.
"""

from agno.agent import Agent
from agno.culture import CultureManager
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# Setup the SQLite database
db = SqliteDb(db_file="tmp/demo.db")

# Define the Culture Manager
culture_manager = CultureManager(model=Claude(id="claude-sonnet-4-5"), db=db)

# Define the Agent
agent = Agent(
    model=Claude(id="claude-sonnet-4-5"), db=db, culture_manager=culture_manager
)

# Run the agent
agent.print_response(
    "What would be the best way to cook vegetarian ramen? Please be detailed and provide a step by step guide."
)
