"""
Entity Memory: Facts and Events
===============================
Semantic vs episodic memory for entities.

Entity Memory stores knowledge about external entities (companies,
people, projects, products). It supports three types of data:

1. **Facts** (Semantic Memory)
   - Timeless truths about the entity
   - "Acme uses PostgreSQL"
   - "Bob is an expert in machine learning"

2. **Events** (Episodic Memory)
   - Time-bound occurrences
   - "Acme launched v2 on Jan 15"
   - "Bob gave a talk at PyCon 2024"

3. **Relationships** (Graph Edges)
   - Connections between entities
   - "Bob is CTO of Acme"
   - "Acme acquired StartupX"

This cookbook focuses on facts and events.

Run:
    python cookbook/15_learning/entity_memory/01_facts_and_events.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import EntityMemoryConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# ============================================================================
# Agent with Entity Memory (AGENTIC mode)
# ============================================================================
agent = Agent(
    name="Entity Facts Agent",
    model=model,
    db=db,
    instructions="""\
You track information about companies, people, and projects.

When users mention entities:
- Extract and save FACTS (timeless truths)
- Extract and save EVENTS (time-bound occurrences)
- Distinguish between the two

Examples:
- FACT: "Acme Corp uses PostgreSQL for their main database"
- EVENT: "Acme Corp raised $50M Series B on March 15, 2024"
- FACT: "The CTO prefers Python over Java"
- EVENT: "The team shipped the new dashboard last week"

Use the entity tools to create entities and add facts/events.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",
            enable_agent_tools=True,
            agent_can_create_entity=True,
            agent_can_update_entity=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Facts (Semantic Memory)
# ============================================================================
def demo_facts():
    """Show storing and retrieving facts about entities."""
    print("=" * 60)
    print("Demo: Facts (Semantic Memory)")
    print("=" * 60)

    user = "facts_demo@example.com"
    session = "facts_session"

    # Share facts about a company
    print("\n--- Share company facts ---\n")
    agent.print_response(
        "Let me tell you about TechStart Inc: "
        "They're a B2B SaaS company in the fintech space. "
        "They use Python and FastAPI for their backend. "
        "Their main database is PostgreSQL with TimescaleDB for time-series data. "
        "The team is about 50 people, fully remote. "
        "Please save this information.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Retrieve facts later
    print("\n--- Retrieve facts ---\n")
    agent.print_response(
        "What do we know about TechStart Inc's technology stack?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Events (Episodic Memory)
# ============================================================================
def demo_events():
    """Show storing and retrieving events about entities."""
    print("\n" + "=" * 60)
    print("Demo: Events (Episodic Memory)")
    print("=" * 60)

    user = "events_demo@example.com"
    session = "events_session"

    # Share events
    print("\n--- Share company events ---\n")
    agent.print_response(
        "Some updates on Acme Corp: "
        "They raised a $30M Series A on January 10, 2025. "
        "Last week they launched their API v2 with breaking changes. "
        "Yesterday they announced a partnership with BigCloud. "
        "They're planning to open a London office in Q2. "
        "Please track these events.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Retrieve events
    print("\n--- Retrieve events ---\n")
    agent.print_response(
        "What recent things have happened with Acme Corp?",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Demo: Mixed Facts and Events
# ============================================================================
def demo_mixed():
    """Show facts and events together."""
    print("\n" + "=" * 60)
    print("Demo: Mixed Facts and Events")
    print("=" * 60)

    user = "mixed_demo@example.com"
    session = "mixed_session"

    # Information dump with both types
    print("\n--- Mixed information ---\n")
    agent.print_response(
        "Notes from my meeting with DataPipe: "
        "The company is based in San Francisco (fact). "
        "They build real-time ETL infrastructure (fact). "
        "Their CTO is Marcus Chen (fact). "
        "Marcus mentioned they use Rust for performance-critical code (fact). "
        "They just hit 1000 customers last month (event). "
        "They're launching a free tier next quarter (event). "
        "The Series B closed at $80M two weeks ago (event). "
        "Please organize and save all this.",
        user_id=user,
        session_id=session,
        stream=True,
    )

    # Query both
    print("\n--- Query entity ---\n")
    agent.print_response(
        "Give me a complete picture of DataPipe - both the stable facts "
        "and the recent developments.",
        user_id=user,
        session_id=session + "_2",
        stream=True,
    )


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_facts()
    demo_events()
    demo_mixed()

    print("\n" + "=" * 60)
    print("✅ Entity Memory supports facts and events")
    print("   Facts = timeless truths (semantic memory)")
    print("   Events = time-bound occurrences (episodic memory)")
    print("=" * 60)
