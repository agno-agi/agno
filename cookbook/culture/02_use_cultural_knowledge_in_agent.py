"""Use cultural knowledge with your Agents.

This example demonstrates how an Agent reads and applies
the cultural knowledge created earlier (see `01_create_cultural_knowledge.py`).

When `add_culture_to_context=True`, the Agent:
- Loads relevant cultural knowledge from the database
- Adds it to the context with instructions on how to use it.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude

# ---------------------------------------------------------------------------
# Step 1. Initialize the database (same one used in 01_create_cultural_knowledge.py)
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/demo.db")

# ---------------------------------------------------------------------------
# Step 2. Initialize the Agent with cultural knowledge enabled
# ---------------------------------------------------------------------------
# The Agent will automatically load shared cultural knowledge (e.g., how to
# format responses, how to write tutorials, or tone/style preferences).
agent = Agent(
    model=Claude(id="claude-sonnet-4-5"),
    db=db,
    # This flag will add the cultural knowledge to the agent's context:
    add_culture_to_context=True,
    # This flag will update cultural knowledge after every run:
    # update_cultural_knowledge=True,
)

# (Optional) Quick A/B switch to show the difference without culture:
# agent_no_culture = Agent(model=Claude(id="claude-sonnet-4-5"))

# ---------------------------------------------------------------------------
# Step 3. Ask the Agent to generate a response that benefits from culture
# ---------------------------------------------------------------------------
# If `01_create_cultural_knowledge.py` added principles like:
#   "Start technical explanations with code examples and then reasoning"
# The Agent will apply that here, starting with a concrete FastAPI example.
print("\n=== With Culture ===\n")
agent.print_response(
    "How do I set up a FastAPI service using Docker? ",
    stream=True,
    markdown=True,
)

# (Optional) Run without culture for contrast:
# print("\n=== Without Culture ===\n")
# agent_no_culture.print_response("How do I set up a FastAPI service using Docker?", stream=True, markdown=True)
