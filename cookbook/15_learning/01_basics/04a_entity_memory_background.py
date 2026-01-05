"""
Entity Memory: Background Mode
==============================
Entity Memory stores knowledge about external things:
- Companies, people, projects
- Facts, events, relationships
- Shared context across users

BACKGROUND mode automatically extracts entity information from conversations.
No explicit tool calls - entities are discovered and saved behind the scenes.

Compare with: 04b_entity_memory_agentic.py for explicit tool-based management.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# BACKGROUND mode: Entities are extracted automatically after responses.
# The agent doesn't see memory tools - extraction happens invisibly.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.BACKGROUND,
            namespace="global",
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show entities
# =============================================================================
def show_entities(namespace: str = "global") -> None:
    """Display stored entities."""
    from rich.pretty import pprint

    store = agent.learning.entity_memory_store
    entities = store.search(query="", namespace=namespace) if store else []
    pprint(entities) if entities else print("\nNo entities stored yet.")


# ============================================================================
# Demo: Automatic Entity Extraction
# ============================================================================
if __name__ == "__main__":
    user_id = "entity_bg@example.com"

    # Session 1: Discuss companies naturally
    print("\n" + "=" * 60)
    print("SESSION 1: Discuss entities (extraction happens automatically)")
    print("=" * 60 + "\n")
    agent.print_response(
        "I just had a meeting with Acme Corp. They're a fintech startup "
        "in San Francisco using Python and PostgreSQL. Their CTO Jane Smith "
        "seemed really interested in our analytics platform.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Entities ---")
    show_entities()

    # Session 2: Add more context
    print("\n" + "=" * 60)
    print("SESSION 2: More entity information")
    print("=" * 60 + "\n")
    agent.print_response(
        "Acme Corp just closed their Series B - $50M led by Sequoia. "
        "Jane mentioned they're hiring 20 more engineers.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("\n--- Updated Entities ---")
    show_entities()

    # Session 3: Query stored knowledge
    print("\n" + "=" * 60)
    print("SESSION 3: Recall entity information")
    print("=" * 60 + "\n")
    agent.print_response(
        "What do we know about Acme Corp and Jane Smith?",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    print("\n--- Final Entities ---")
    show_entities()
