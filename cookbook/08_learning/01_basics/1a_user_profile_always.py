"""
User Profile: Always Mode
=========================
User Profile captures structured profile fields about users:
- Name and preferred name
- Custom profile fields (when using extended schemas)

ALWAYS mode extracts profile information automatically in parallel
while the agent responds - no explicit tool calls needed.

Compare with: 1b_user_profile_agentic.py for explicit tool-based updates.
See also: 2a_user_memory_always.py for unstructured observations.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ALWAYS mode: Extraction happens automatically after each response.
# The agent doesn't see or call any profile tools - it's invisible.
# UserProfile stores structured fields (name, preferred_name, custom fields)
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        user_profile=UserProfileConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "alice@example.com"

    # Session 1: Share information naturally
    print("\n" + "=" * 60)
    print("SESSION 1: Share information (extraction happens automatically)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Hi! I'm Alice Chen, but please call me Ali.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)

    # Session 2: New session - profile is recalled automatically
    print("\n" + "=" * 60)
    print("SESSION 2: Profile recalled in new session")
    print("=" * 60 + "\n")

    agent.print_response(
        "What's my name again?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)
