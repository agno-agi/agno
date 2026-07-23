"""
Extraction Limits: Preventing Runaway Loops
============================================
Configure max_updates_per_run to cap memory updates per extraction.

When learning stores extract information, they call tools (add_memory,
update_profile, etc.) in a loop. Without limits, a model that keeps
requesting tools can loop indefinitely.

max_updates_per_run caps tool executions:
- LearningMachine level: applies to all stores (default: 10)
- Store config level: overrides the global for that store
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    EntityMemoryConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Global max_updates_per_run=5 applies to all stores unless overridden.
# user_profile: inherits 5 from LearningMachine
# user_memory: explicit override to 3
# entity_memory: explicit override to 15 (dense entity info needs more)
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=LearningMachine(
        max_updates_per_run=5,
        user_profile=UserProfileConfig(mode=LearningMode.ALWAYS),
        user_memory=UserMemoryConfig(mode=LearningMode.ALWAYS, max_updates_per_run=3),
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.ALWAYS, max_updates_per_run=15
        ),
    ),
    markdown=True,
    debug_mode=True,  # Shows "Tool call limit reached" logs
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "demo@example.com"
    session_id = "extraction-limits-demo"

    # Dense prompt with lots of information to extract
    print("\n" + "=" * 70)
    print("DENSE INFO DUMP (triggers many extraction attempts)")
    print("=" * 70)
    print("User profile limit: 5 (global)")
    print("User memory limit: 3 (override)")
    print("Entity memory limit: 15 (override)")
    print("=" * 70 + "\n")

    agent.print_response(
        "Hi, I'm Sarah Chen, VP of Engineering at TechCorp. "
        "I prefer detailed technical explanations with code examples. "
        "I work remotely from Seattle and focus on distributed systems. "
        "Quick context on our team: "
        "Marcus Lee is our CTO, he reports to CEO Jane Smith. "
        "Alice Wang leads Backend, Bob Martinez leads DevOps. "
        "We use PostgreSQL, Redis, and Kubernetes. "
        "Last week we migrated to AWS us-west-2. "
        "Our Series B closed at $50M last month.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )

    # Show what was captured
    lm = agent.learning_machine
    print("\n" + "=" * 70)
    print("EXTRACTION RESULTS")
    print("=" * 70)

    print("\n--- User Profile (limit: 5) ---")
    lm.user_profile_store.print(user_id=user_id)

    print("\n--- User Memory (limit: 3) ---")
    lm.user_memory_store.print(user_id=user_id)

    print("\n--- Entity Memory (limit: 15) ---")
    from rich.pretty import pprint

    entities = lm.entity_memory_store.search(query="techcorp", limit=20)
    if entities:
        pprint(entities)
    else:
        print("No entities found")

    print("\n" + "=" * 70)
    print("Check debug logs above for 'Tool call limit reached' messages")
    print("=" * 70)
