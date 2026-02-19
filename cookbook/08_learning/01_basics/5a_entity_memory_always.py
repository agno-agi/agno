"""
Entity Memory: Always Mode
==========================
Entity Memory stores knowledge about external things:
- Companies, people, projects
- Facts, events, relationships
- Shared context across users

ALWAYS mode automatically extracts entity information from conversations.
No explicit tool calls - entities are discovered and saved behind the scenes.

Compare with: 5b_entity_memory_agentic.py for explicit tool-based management.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ALWAYS mode: Entities are extracted automatically after responses.
# The agent doesn't see memory tools - extraction happens invisibly.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions="You're a sales assistant. Acknowledge notes briefly.",
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.ALWAYS,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.pretty import pprint

    user_id = "sales@example.com"

    # Session 1: Mention entities naturally
    print("\n" + "=" * 60)
    print("SESSION 1: Discuss entities (extraction happens automatically)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Just met with Acme Corp. They're a fintech startup in SF, "
        "50 employees. CTO is Jane Smith. They use Python and Postgres.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    print("\n--- Extracted Entities ---")
    entities = agent.learning_machine.entity_memory_store.search(query="acme", limit=10)
    pprint(entities)

    # Session 2: Add more info about same entity
    print("\n" + "=" * 60)
    print("SESSION 2: Update same entity")
    print("=" * 60 + "\n")

    agent.print_response(
        "Update on Acme Corp: they just raised $50M Series B from Sequoia. "
        "Jane Smith mentioned they're hiring 20 engineers.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    print("\n--- Updated Entities ---")
    entities = agent.learning_machine.entity_memory_store.search(query="acme", limit=10)
    pprint(entities)
