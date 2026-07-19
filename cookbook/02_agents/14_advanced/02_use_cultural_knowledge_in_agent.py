"""
02 Use Cultural Knowledge In Agent
=============================

Use cultural knowledge with your Agents.
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
# The Agent will automatically load shared cultural knowledge (e.g., how to
# format responses, how to write tutorials, or tone/style preferences).
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    # This flag will add the cultural knowledge to the agent's context:
    add_culture_to_context=True,
    # This flag will update cultural knowledge after every run:
    # update_cultural_knowledge=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # (Optional) Quick A/B switch to show the difference without culture:
    # agent_no_culture = Agent(model=OpenAIResponses(id="gpt-5.2"))

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
