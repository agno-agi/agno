"""Run `uv pip install ddgs openai` to install dependencies."""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = InMemoryDb()

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(db=db)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # The Agent sessions will now be stored in the in-memory database
    agent.print_response("Give me an easy and healthy dinner recipe")
