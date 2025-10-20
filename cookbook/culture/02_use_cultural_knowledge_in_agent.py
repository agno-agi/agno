"""
Use cultural knowledge with your Agents.

This example demonstrates how an Agent automatically reads and applies
the cultural knowledge created earlier (see `01_create_cultural_knowledge.py`).

When `enable_agent_culture=True`, the Agent:
- Loads relevant cultural knowledge from the database.
- Applies shared norms, rules, and best practices during reasoning.
- May add or update cultural knowledge based on new insights.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Step 1. Initialize the database with existing cultural knowledge
# ---------------------------------------------------------------------------
# The same SQLite file used in `01_create_cultural_knowledge.py`
db = SqliteDb(db_file="tmp/demo.db")

# ---------------------------------------------------------------------------
# Step 2. Initialize the Agent with cultural knowledge enabled
# ---------------------------------------------------------------------------
# The Agent will automatically load shared cultural knowledge (e.g., how to
# format responses, how to write tutorials, or tone/style preferences).
agent = Agent(
    db=db,
    # This flag will add the cultural knowledge to the agent's context
    add_culture_to_context=True,
    # This flag will enable the agent to add or update cultural knowledge automatically
    enable_agent_culture=True,
    # This flag will run the CultureManager after every run
    # update_cultural_knowledge=True,
    model=Claude(id="claude-sonnet-4-5"),
)

# ---------------------------------------------------------------------------
# Step 3. Ask the Agent to generate a response that benefits from culture
# ---------------------------------------------------------------------------
# If `01_create_cultural_knowledge.py` added principles like:
#   "Start technical explanations with code examples and then reasoning"
# The Agent will apply that here, starting with a concrete FastAPI example.
agent.print_response(
    "Create a short tutorial on how to set up a FastAPI service using Docker. "
)
