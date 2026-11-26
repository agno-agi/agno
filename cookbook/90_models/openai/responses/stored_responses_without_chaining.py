"""Keep OpenAI response logs while Agno controls the history sent on each turn."""

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(
        id="gpt-5.6-luna",
        store=True,
        use_previous_response_id=False,
    ),
    db=InMemoryDb(),
    session_id="stored-responses-without-chaining",
    add_history_to_context=True,
    num_history_runs=2,
    instructions="Answer briefly using the conversation history when relevant.",
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "My project is called Cedar. Remember its name for our conversation."
    )
    agent.print_response("What is my project called?", stream=True)
