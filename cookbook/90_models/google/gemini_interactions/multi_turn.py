"""
Gemini Interactions - Multi-turn Conversation
==============================================

Demonstrates server-side conversation history with the Interactions API.
After the first response, subsequent turns only send the new message
and reference the previous interaction via `previous_interaction_id`.
This enables implicit caching and reduces token costs.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import GeminiInteractions

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=GeminiInteractions(id="gemini-3-flash-preview"),
    add_history_to_context=True,
    db=SqliteDb(db_file="tmp/data.db"),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # First turn - establishes the interaction
    agent.print_response("My name is Alice and I love hiking in the mountains.")

    # Second turn - references the previous interaction for context
    agent.print_response("What did I just tell you about myself?")

    # Third turn - continues the conversation chain
    agent.print_response(
        "Suggest a hiking destination based on what you know about me."
    )
