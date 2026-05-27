"""
03 Automatic Cultural Management
=============================

Automatically update cultural knowledge based on Agent interactions.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Step 1. Initialize the database (same one used in 01_create_cultural_knowledge.py)
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/demo.db")

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
# The Agent will automatically add or update cultural knowledge after each run.
agent = Agent(
    db=db,
    model=OpenAIResponses(id="gpt-5.2"),
    update_cultural_knowledge=True,  # enables automatic cultural updates
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # ---------------------------------------------------------------------------
    # Step 3. Ask the Agent to generate a response
    # ---------------------------------------------------------------------------
    agent.print_response(
        "What would be the best way to cook ramen? Detailed and specific instructions generally work better than general advice.",
        stream=True,
        markdown=True,
    )
