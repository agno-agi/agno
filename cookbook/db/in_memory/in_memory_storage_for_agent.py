"""Run `pip install ddgs openai` to install dependencies."""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb

# Setup the in-memory database
db = InMemoryDb()

# Setup the agent and pass the database
agent = Agent(db=db)

# The Agent sessions will now be stored in the in-memory database
agent.print_response("Give me an easy and healthy dinner recipe")
