"""
Entity Memory Quick Start
=========================
Entity Memory stores knowledge about things other than the user:
- Companies, people, projects
- Facts, events, relationships
- Shared context across users

This example uses AGENTIC mode with tools, so the agent decides
when to save and retrieve entity information.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Create Agent
# ============================================================================
# Entity memory tracks external entities (not the user).
# With enable_agent_tools=True, the agent gets save/search tools.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    instructions="Track companies and people mentioned in conversations.",
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
            enable_agent_tools=True,
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
    entities = store.list(namespace=namespace) if store else []
    pprint(entities) if entities else print("\nNo entities stored yet.")


# ============================================================================
# Demo: Track External Entities
# ============================================================================
if __name__ == "__main__":
    user_id = "entity@example.com"

    # Session 1: Share entity information
    print("\n" + "=" * 60)
    print("SESSION 1: Share entity information")
    print("=" * 60 + "\n")
    agent.print_response(
        "Acme Corp is a fintech startup in San Francisco. "
        "They use Python and PostgreSQL. Their CTO is Jane Smith.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Entities ---")
    show_entities()

    # Session 2: Query entities
    print("\n" + "=" * 60)
    print("SESSION 2: Query entities")
    print("=" * 60 + "\n")
    agent.print_response(
        "What do we know about Acme Corp?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("\n--- Updated Entities ---")
    show_entities()
