"""
Session Context Learning
===========================================
Session context captures a summary of the current conversation.

Unlike user profiles (which accumulate over time), session context
is a snapshot that gets replaced on each extraction.

Use this for:
- Long conversations where early context might be lost
- Multi-turn tasks that need continuity
- Resuming conversations after breaks
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, SessionContextConfig
from agno.models.openai import OpenAIChat

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# =============================================================================
# Create Learning Agent with Session Context
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        user_profile=True,  # Keep user profile enabled
        session_context=SessionContextConfig(),  # Enable session summaries
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show session context
# =============================================================================
def show_context(session_id: str):
    """Display the stored session context."""
    context = agent.learning.stores["session_context"].get(session_id=session_id)
    if context and context.summary:
        print("\n📋 Session Context:")
        print(f"   Summary: {context.summary}")
    else:
        print("\n📋 No session context yet.")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "carol@example.com"
    session_id = "debug_session"

    # --- Turn 1: Start debugging ---
    print("=" * 60)
    print("Turn 1: User describes a problem")
    print("=" * 60)
    agent.print_response(
        "I'm getting a weird error in my Python code. When I try to import "
        "pandas, it says 'ModuleNotFoundError' but I'm sure I installed it.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 2: Add more context ---
    print("=" * 60)
    print("Turn 2: More details")
    print("=" * 60)
    agent.print_response(
        "I'm using a virtual environment. I activated it with 'source venv/bin/activate'. "
        "The pip list shows pandas is installed.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 3: Resolution ---
    print("=" * 60)
    print("Turn 3: Working toward solution")
    print("=" * 60)
    agent.print_response(
        "Oh wait, I think I might have multiple Python versions. How do I check which one is being used?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    show_context(session_id)

    # --- Turn 4: Resume after break ---
    print("=" * 60)
    print("Turn 4: Resume conversation (context preserved)")
    print("=" * 60)
    agent.print_response(
        "I'm back. Where were we with the pandas issue?",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
