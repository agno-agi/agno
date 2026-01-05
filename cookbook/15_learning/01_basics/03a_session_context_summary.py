"""
Session Context Quick Start
===========================
Track conversation state across runs.

Session Context captures state for the current conversation:
- Summary of what's been discussed
- Current goals and progress
- Key decisions made

This example uses summary-only mode for fast, lightweight tracking.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# Session context tracks the current conversation's state.
# Unlike user profile (long-term), this is ephemeral per session.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=False,  # Summary only (faster)
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show session context
# =============================================================================
def show_context(user_id: str, session_id: str) -> None:
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
    session_id = "api_design_session"

    # Turn 1: Start a project discussion
    print("\n" + "=" * 60)
    print("TURN 1: Start project")
    print("=" * 60 + "\n")
    agent.print_response(
        "I'm building a REST API for a todo app. Help me design it.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(user_id, session_id)

    # Turn 2: Continue the discussion
    print("\n" + "=" * 60)
    print("TURN 2: Dive deeper")
    print("=" * 60 + "\n")
    agent.print_response(
        "What endpoints should I create for tasks?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(user_id, session_id)

    # Turn 3: Test recall
    print("\n" + "=" * 60)
    print("TURN 3: Test context recall")
    print("=" * 60 + "\n")
    agent.print_response(
        "Summarize what we've decided so far.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Final Context ---")
    show_context(user_id, session_id)
