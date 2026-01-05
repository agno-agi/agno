"""
Session Context: Summary Mode
=============================
Session Context tracks the current conversation's state:
- What's been discussed
- Key decisions made
- Important context

SUMMARY mode (enable_planning=False) provides lightweight tracking -
just a running summary of the conversation without goal/plan tracking.

Compare with: 03b_session_context_planning.py for goal-oriented tracking.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# Summary mode: Just tracks what's been discussed, no planning overhead.
# Good for general conversations where you want continuity without structure.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=False,  # Summary only
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show session context
# =============================================================================
def show_context(session_id: str) -> None:
    """Display the stored session context."""
    from rich.pretty import pprint

    store = agent.learning.session_context_store
    context = store.get(session_id=session_id) if store else None
    pprint(context) if context else print("\nNo context stored yet.")


# ============================================================================
# Demo: Multi-Turn Conversation
# ============================================================================
if __name__ == "__main__":
    user_id = "session@example.com"
    session_id = "api_design"

    # Turn 1: Quick focused question
    print("\n" + "=" * 60)
    print("TURN 1: Start discussion")
    print("=" * 60 + "\n")
    agent.print_response(
        "I'm building a todo app API. What's the single most important "
        "endpoint to implement first? Just one.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(session_id)

    # Turn 2: Follow-up
    print("\n" + "=" * 60)
    print("TURN 2: Follow-up")
    print("=" * 60 + "\n")
    agent.print_response(
        "Good. What HTTP method and path would you use for that?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(session_id)

    # Turn 3: Test recall
    print("\n" + "=" * 60)
    print("TURN 3: Test context recall")
    print("=" * 60 + "\n")
    agent.print_response(
        "What endpoint did we decide on?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Final Context ---")
    show_context(session_id)
