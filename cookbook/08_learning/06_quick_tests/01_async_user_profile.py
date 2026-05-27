"""
Async User Profile Test
=======================
Tests the async path for user profile learning.

All other cookbooks use sync (print_response). This test verifies
that the async path (aprint_response) works correctly.

This is critical because:
- Background learning uses asyncio tasks in async mode
- Different code paths for aprocess vs process
- Potential race conditions in async context
"""

import asyncio

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
# Run Async Demo
# ---------------------------------------------------------------------------


async def main():
    user_id = "async_test@example.com"

    # Session 1: Share information (async)
    print("\n" + "=" * 60)
    print("SESSION 1: Async - Share information")
    print("=" * 60 + "\n")

    await agent.aprint_response(
        "Hi! I'm Diana Prince, but call me Di.",
        user_id=user_id,
        session_id="async_session_1",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)

    # Session 2: New session - verify profile persisted (async)
    print("\n" + "=" * 60)
    print("SESSION 2: Async - Profile recall")
    print("=" * 60 + "\n")

    await agent.aprint_response(
        "What's my name?",
        user_id=user_id,
        session_id="async_session_2",
        stream=True,
    )
    agent.learning_machine.user_profile_store.print(user_id=user_id)

    print("\n" + "=" * 60)
    print("ASYNC TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
