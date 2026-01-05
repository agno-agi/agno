"""
Session Context: Planning Mode
==============================
Session Context tracks the current conversation's state:
- What's been discussed
- Current goals and their status
- Active plans and progress
- Blockers and next steps

PLANNING mode (enable_planning=True) adds structured goal tracking -
the agent can set goals, track progress, and mark completion.

Compare with: 03a_session_context_summary.py for lightweight tracking.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# Planning mode: Tracks goals, plans, and progress in addition to summary.
# Good for task-oriented conversations where you want structured progress.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    instructions="Help users accomplish their goals. Track progress and next steps.",
    learning=LearningMachine(
        session_context=SessionContextConfig(
            enable_planning=True,  # Enable goal/plan tracking
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
# Demo: Goal-Oriented Conversation
# ============================================================================
if __name__ == "__main__":
    user_id = "planner@example.com"
    session_id = "migration_project"

    # Turn 1: Define a focused goal
    print("\n" + "=" * 60)
    print("TURN 1: Define goal")
    print("=" * 60 + "\n")
    agent.print_response(
        "I need to migrate from MySQL to PostgreSQL. "
        "What are the 3 main steps? Brief list only.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(session_id)

    # Turn 2: Work on first step
    print("\n" + "=" * 60)
    print("TURN 2: First step detail")
    print("=" * 60 + "\n")
    agent.print_response(
        "For step 1, what's the one command I should run first?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(session_id)

    # Turn 3: Progress update
    print("\n" + "=" * 60)
    print("TURN 3: Mark progress")
    print("=" * 60 + "\n")
    agent.print_response(
        "Done with step 1. What's step 2 again?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Session Context ---")
    show_context(session_id)

    # Turn 4: Check progress
    print("\n" + "=" * 60)
    print("TURN 4: Check progress")
    print("=" * 60 + "\n")
    agent.print_response(
        "How many steps have we completed vs remaining?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Final Context ---")
    show_context(session_id)
