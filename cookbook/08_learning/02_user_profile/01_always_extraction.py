"""
User Profile: Always Extraction (Deep Dive)
============================================
Automatic profile extraction from natural conversation.

ALWAYS mode extracts profile information in the background after each response.
The user doesn't see tools - extraction happens invisibly.

This example shows gradual profile building across multiple conversations.

Compare with: 02_agentic_mode.py for explicit tool-based updates.
See also: 01_basics/1a_user_profile_always.py for the basics.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

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
# Run: Gradual Profile Building
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "marcus@example.com"

    # Conversation 1: Basic introduction
    print("\n" + "=" * 60)
    print("CONVERSATION 1: Basic introduction")
    print("=" * 60 + "\n")

    agent.print_response(
        "Hi! I'm Marcus, nice to meet you.",
        user_id=user_id,
        session_id="conv_1",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)

    # Conversation 2: Share work context
    print("\n" + "=" * 60)
    print("CONVERSATION 2: Work context")
    print("=" * 60 + "\n")

    agent.print_response(
        "I'm a senior engineer at Stripe, focusing on payment systems.",
        user_id=user_id,
        session_id="conv_2",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)

    # Conversation 3: Preferences
    print("\n" + "=" * 60)
    print("CONVERSATION 3: Preferences (implicit extraction)")
    print("=" * 60 + "\n")

    agent.print_response(
        "I prefer code examples over long explanations. "
        "I'm very familiar with Python and Go.",
        user_id=user_id,
        session_id="conv_3",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)

    # Conversation 4: Nickname
    print("\n" + "=" * 60)
    print("CONVERSATION 4: Preferred name update")
    print("=" * 60 + "\n")

    agent.print_response(
        "By the way, most people call me Marc.",
        user_id=user_id,
        session_id="conv_4",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)
