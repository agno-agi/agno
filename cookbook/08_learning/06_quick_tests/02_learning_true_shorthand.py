"""
Learning=True Shorthand Test
============================
Tests the simplest way to enable learning: `learning=True`.

This is the most common user pattern and must work flawlessly.

When learning=True:
- A default LearningMachine is created
- UserProfile is enabled with ALWAYS mode (structured fields)
- UserMemory is enabled with ALWAYS mode (unstructured observations)
- db and model are injected from the agent

This test verifies the shorthand works identically to explicit config.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent - Using the simplest possible configuration
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# This is the simplest way to enable learning - just set learning=True
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=True,  # <-- The shorthand we're testing
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "shorthand_test@example.com"

    # Note: LearningMachine is lazily initialized - only set up when agent runs
    print("\n" + "=" * 60)
    print("SESSION 1: Share information (learning=True shorthand)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Hi! I'm Charlie Brown. Friends call me Chuck.",
        user_id=user_id,
        session_id="shorthand_session_1",
        stream=True,
    )

    # Verify LearningMachine was created (after first run)
    print("\n" + "=" * 60)
    print("VERIFICATION: LearningMachine created from learning=True")
    print("=" * 60 + "\n")

    lm = agent.learning_machine
    print(f"LearningMachine exists: {lm is not None}")
    print(
        f"UserProfileStore exists: {lm.user_profile_store is not None if lm else False}"
    )
    print(
        f"UserMemoryStore exists: {lm.user_memory_store is not None if lm else False}"
    )
    print(f"DB injected: {lm.db is not None if lm else False}")
    print(f"Model injected: {lm.model is not None if lm else False}")

    if not lm:
        print("\nFAILED: LearningMachine was not created!")
        exit(1)

    if not lm.user_profile_store:
        print("\nFAILED: UserProfileStore was not created!")
        exit(1)

    if not lm.user_memory_store:
        print("\nFAILED: UserMemoryStore was not created!")
        exit(1)

    print("\n--- User Profile ---")
    lm.user_profile_store.print(user_id=user_id)

    print("\n--- User Memory ---")
    lm.user_memory_store.print(user_id=user_id)

    # Session 2: Verify profile persisted
    print("\n" + "=" * 60)
    print("SESSION 2: Profile recall")
    print("=" * 60 + "\n")

    agent.print_response(
        "What do my friends call me?",
        user_id=user_id,
        session_id="shorthand_session_2",
        stream=True,
    )

    print("\n--- User Profile ---")
    lm.user_profile_store.print(user_id=user_id)

    print("\n--- User Memory ---")
    lm.user_memory_store.print(user_id=user_id)

    print("\n" + "=" * 60)
    print("SHORTHAND TEST COMPLETE")
    print("=" * 60)
