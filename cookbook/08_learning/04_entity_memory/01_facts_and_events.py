"""
Entity Memory: Facts and Events (Deep Dive)
============================================
Semantic (facts) vs episodic (events) memory for entities.

Entity Memory stores knowledge about external entities:
- Facts: Timeless truths ("Acme uses PostgreSQL")
- Events: Time-bound occurrences ("Acme raised $30M on Jan 15")

AGENTIC mode gives the agent tools to create/update entities.

Compare with: 04_always_extraction.py for automatic extraction.
See also: 01_basics/5a_entity_memory_always.py for the basics.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions=(
        "Track information about companies and people. "
        "Distinguish between facts (timeless) and events (time-bound)."
    ),
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.pretty import pprint

    user_id = "research@example.com"
    session_id = "company_research"

    # Share facts and events
    print("\n" + "=" * 60)
    print("MESSAGE 1: Share mixed facts and events")
    print("=" * 60 + "\n")

    agent.print_response(
        "Notes from my meeting with DataPipe: "
        "They're based in San Francisco. "
        "They build real-time ETL infrastructure in Rust. "
        "Their CTO is Marcus Chen. "
        "They just hit 1000 customers last month. "
        "Series B closed at $80M two weeks ago.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Entities ---")
    pprint(
        agent.learning_machine.entity_memory_store.search(query="datapipe", limit=10)
    )

    # Query the entity
    print("\n" + "=" * 60)
    print("MESSAGE 2: Query the entity")
    print("=" * 60 + "\n")

    agent.print_response(
        "What do we know about DataPipe?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    # Add more events
    print("\n" + "=" * 60)
    print("MESSAGE 3: Add more events")
    print("=" * 60 + "\n")

    agent.print_response(
        "Update on DataPipe: They announced a partnership with BigCloud yesterday. "
        "They're also opening a London office next quarter.",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    print("\n--- Updated Entities ---")
    pprint(
        agent.learning_machine.entity_memory_store.search(query="datapipe", limit=10)
    )
