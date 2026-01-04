"""
Hello Learning
==============
The simplest possible Learning Machine example.

This demonstrates:
- Enabling learning with a single boolean
- Automatic user profile extraction
- Memory persistence across sessions
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# ============================================================================
# Create Learning Agent
# ============================================================================
# Just set learning=True and get sensible defaults:
# - User profile extraction in BACKGROUND mode
# - Automatic memory persistence
# - Context injection into system prompt
agent = Agent(
    name="Hello Learning Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=True,  # That's it!
    markdown=True,
)


# =============================================================================
# Helper: Show user profile
# =============================================================================
def show_profile(user_id: str) -> None:
    """Display the stored user profile."""
    from rich.pretty import pprint

    store = agent.learning.user_profile_store
    profile = store.get(user_id=user_id) if store else None
    print("\n"), pprint(profile) if profile else print("\nNo profile stored yet.")


# ============================================================================
# Demo: Memory Across Sessions
# ============================================================================
if __name__ == "__main__":
    user_id = "hello@learning.com"

    print("Session 1: Introduce yourself")
    print("=" * 60)
    agent.print_response(
        "Hi! I'm Alice, I work at Anthropic as a research scientist. "
        "I love hiking and prefer dark mode in all my apps.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("=" * 60)
    show_profile(user_id)
    print("=" * 60)

    print("Session 2: Test memory recall")
    print("=" * 60)
    agent.print_response(
        "What do you remember about me?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("=" * 60)
    show_profile(user_id)
    print("=" * 60)
