"""
Entity Memory: Agentic Mode
===========================
Entity Memory stores knowledge about external things:
- Companies, people, projects
- Facts, events, relationships
- Shared context across users

AGENTIC mode gives the agent explicit tools to manage entities:
- search_entities, create_entity
- add_fact, add_event, add_relationship

The agent decides when to store and retrieve information.

Compare with: 6_entity_memory_background.py for automatic extraction.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# AGENTIC mode: Agent gets entity tools and decides when to use them.
# You'll see tool calls like "create_entity", "add_fact" in responses.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions="Track important information about companies, people, and projects "
    "using your entity memory tools.",
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
        ),
    ),
    markdown=True,
)

# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    from rich.pretty import pprint

    user_id = "entity_ag@example.com"

    # Session 1: Agent explicitly creates entities
    print("\n" + "=" * 60)
    print("SESSION 1: Share entity info (watch for tool calls)")
    print("=" * 60 + "\n")

    agent.print_response(
        "I need to track information about NorthStar Analytics. "
        "They're a data analytics startup, Series A stage, about 50 employees. "
        "Tech stack is Python, Snowflake, and dbt.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    print("\n--- Created Entities ---")
    entities = agent.learning.entity_memory_store.search(query="northstar", limit=10)
    pprint(entities)

    # Session 2: Add relationships
    print("\n" + "=" * 60)
    print("SESSION 2: Add relationships")
    print("=" * 60 + "\n")

    agent.print_response(
        "Sarah Chen is the VP of Engineering at NorthStar. "
        "She used to work at Databricks.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    print("\n--- Updated Entities ---")
    entities = agent.learning.entity_memory_store.search(query="", limit=10)
    pprint(entities)

    # Session 3: Add events
    print("\n" + "=" * 60)
    print("SESSION 3: Record events")
    print("=" * 60 + "\n")

    agent.print_response(
        "We had our first discovery call with NorthStar yesterday. "
        "They're interested in our ML platform.",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )

    print("\n--- Final Entities ---")
    entities = agent.learning.entity_memory_store.search(query="northstar", limit=10)
    pprint(entities)
