"""
No-DB Graceful Handling Test
============================
Tests that learning gracefully handles missing database.

Users might accidentally enable learning without providing a database.
The system should:
1. Not crash
2. Log a warning (ideally)
3. Still respond to the user
4. Just skip the learning/persistence part

This is critical for user experience - a missing DB should degrade
gracefully, not explode.
"""

from agno.agent import Agent
from agno.learn import LearningMachine, LearningMode, UserProfileConfig
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent - Intentionally NO database
# ---------------------------------------------------------------------------

# Note: No db parameter - this is the edge case we're testing
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
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
    user_id = "no_db_test@example.com"

    print("\n" + "=" * 60)
    print("TEST: Learning enabled WITHOUT database")
    print("=" * 60 + "\n")

    # Check that LearningMachine exists but has no DB
    lm = agent.learning_machine
    print(f"LearningMachine exists: {lm is not None}")
    if lm:
        print(f"DB is None: {lm.db is None}")
        print(f"UserProfileStore exists: {lm.user_profile_store is not None}")

    # This should NOT crash - it should respond normally
    print("\n" + "=" * 60)
    print("SESSION 1: Should respond without crashing")
    print("=" * 60 + "\n")

    try:
        agent.print_response(
            "Hi! I'm Eve. Nice to meet you.",
            user_id=user_id,
            session_id="no_db_session_1",
            stream=True,
        )
        print("\n[OK] Agent responded without crashing")
    except Exception as e:
        print(f"\n[FAILED] Agent crashed: {e}")
        exit(1)

    # Try to print profile - should handle gracefully
    print("\n" + "=" * 60)
    print("PROFILE CHECK: Should show empty (no DB to persist)")
    print("=" * 60 + "\n")

    if lm and lm.user_profile_store:
        lm.user_profile_store.print(user_id=user_id)

    # Second message - should also not crash
    print("\n" + "=" * 60)
    print("SESSION 2: Second message should also work")
    print("=" * 60 + "\n")

    try:
        agent.print_response(
            "What's my name?",
            user_id=user_id,
            session_id="no_db_session_2",
            stream=True,
        )
        print("\n[OK] Second message worked")
    except Exception as e:
        print(f"\n[FAILED] Second message crashed: {e}")
        exit(1)

    print("\n" + "=" * 60)
    print("NO-DB GRACEFUL TEST COMPLETE")
    print("Expected: Agent works, but profile not persisted")
    print("=" * 60)
