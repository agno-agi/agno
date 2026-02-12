"""
Entity Memory: Relationships (Deep Dive)
========================================
Graph edges between entities.

Relationships connect entities to form a knowledge graph:
- "Bob is CTO of Acme"
- "Acme acquired StartupX"
- "API Gateway depends on Auth Service"

AGENTIC mode lets the agent create entities and add relationships.

Compare with: 01_facts_and_events.py for facts/events.
See also: 01_basics/5b_entity_memory_agentic.py for the basics.
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
        "Build a knowledge graph of entities and their relationships. "
        "Use appropriate relation types: works_at, reports_to, acquired, depends_on, etc."
    ),
    learning=LearningMachine(
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from rich.pretty import pprint

    user_id = "org@example.com"
    session_id = "org_session"

    # Define org structure
    print("\n" + "=" * 60)
    print("MESSAGE 1: Define org structure")
    print("=" * 60 + "\n")

    agent.print_response(
        "TechCorp's leadership: "
        "Sarah Chen is the CEO and founder. "
        "Bob Martinez is the CTO, reporting to Sarah. "
        "Alice Kim leads Engineering under Bob. "
        "DevOps and Backend teams report to Alice.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    print("\n--- Entities ---")
    pprint(
        agent.learning_machine.entity_memory_store.search(query="techcorp", limit=10)
    )

    # Query relationships
    print("\n" + "=" * 60)
    print("MESSAGE 2: Query relationships")
    print("=" * 60 + "\n")

    agent.print_response(
        "Who reports to Bob Martinez?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    # Add more relationships
    print("\n" + "=" * 60)
    print("MESSAGE 3: Company relationships")
    print("=" * 60 + "\n")

    agent.print_response(
        "TechCorp just acquired StartupAI for $50M. "
        "They also partnered with CloudCo on infrastructure.",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    print("\n--- Updated Entities ---")
    pprint(
        agent.learning_machine.entity_memory_store.search(query="techcorp", limit=10)
    )
