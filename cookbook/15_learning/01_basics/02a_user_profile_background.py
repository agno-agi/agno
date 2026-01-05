"""
User Profile: Background Mode
=============================
User Profile captures long-term information about users:
- Name and preferences
- Work context
- Communication style
- Any memorable facts

BACKGROUND mode extracts user information automatically in parallel
while the agent responds - no explicit tool calls needed.

Compare with: 02b_user_profile_agentic.py for explicit tool-based extraction.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# BACKGROUND mode: Extraction happens automatically after each response.
# The agent doesn't see or call any memory tools - it's invisible.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
    ),
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
    pprint(profile) if profile else print("\nNo profile stored yet.")


# ============================================================================
# Demo: Automatic Memory Extraction
# ============================================================================
if __name__ == "__main__":
    user_id = "background@example.com"

    # Session 1: Share information naturally
    print("\n" + "=" * 60)
    print("SESSION 1: Share information (extraction happens automatically)")
    print("=" * 60 + "\n")
    agent.print_response(
        "Hi! I'm Alice, I work at Anthropic as a research scientist. "
        "I love hiking and prefer dark mode in all my apps.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Profile ---")
    show_profile(user_id)

    # Session 2: Test memory recall
    print("\n" + "=" * 60)
    print("SESSION 2: New session, test memory")
    print("=" * 60 + "\n")
    agent.print_response(
        "What do you remember about me?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("\n--- Updated Profile ---")
    show_profile(user_id)
