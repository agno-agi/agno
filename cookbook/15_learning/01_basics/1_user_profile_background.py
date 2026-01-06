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

Compare with: 2_user_profile_agentic.py for explicit tool-based updates.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIChat

# ============================================================================
# Setup
# ============================================================================

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# BACKGROUND mode: Extraction happens automatically after each response.
# The agent doesn't see or call any memory tools - it's invisible.
agent = Agent(
    model=OpenAIChat(id="gpt-4.1"),
    db=db,
    learning=LearningMachine(
        db=db,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
        ),
    ),
    markdown=True,
)

# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    user_id = "alice@example.com"

    # Session 1: Share information naturally
    print("\n" + "=" * 60)
    print("SESSION 1: Share information (extraction happens automatically)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Hi! I'm Alice, I work at Anthropic as a research scientist. "
        "I prefer concise responses without too much explanation.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    agent.learning.user_profile_store.print(user_id=user_id)

    # Session 2: New session - profile is recalled automatically
    print("\n" + "=" * 60)
    print("SESSION 2: Profile recalled in new session")
    print("=" * 60 + "\n")

    agent.print_response(
        "What's a good Python library for async HTTP requests?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
