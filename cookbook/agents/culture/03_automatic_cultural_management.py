"""Automatically update cultural knowledge based on Agent interactions.

This example demonstrates how an Agent can autonomously add or refine
shared cultural knowledge after completing a task.

When `update_cultural_knowledge=True`, the Agent:
- Reflects on its interaction and reasoning process.
- Identifies reusable insights, patterns, or rules.
- Updates or adds relevant cultural knowledge to the database.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Step 1. Initialize the database (same one used in 01_create_cultural_knowledge.py)
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/demo.db")

# ---------------------------------------------------------------------------
# Step 2. Initialize the Agent with automatic cultural management enabled
# ---------------------------------------------------------------------------
# The Agent will automatically add or update cultural knowledge after each run.
agent = Agent(
    db=db,
    model=Claude(id="claude-sonnet-4-5"),
    update_cultural_knowledge=True,  # enables automatic cultural updates
)

# ---------------------------------------------------------------------------
# Step 3. Ask the Agent to generate a response
# ---------------------------------------------------------------------------
agent.print_response(
    "What would be the best way to cook ramen? Detailed and specific instructions generally work better than general advice.",
    stream=True,
    markdown=True,
)
