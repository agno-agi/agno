"""
Entity Memory Quick Start
=========================
Entity knowledge tracking in 30 lines.

Entity Memory captures knowledge about external entities:
- Companies, projects, people, products, systems
- Facts (semantic): "Acme uses PostgreSQL"
- Events (episodic): "Acme launched v2 on Jan 15"
- Relationships (graph): "Bob is CTO of Acme"

Run:
    python cookbook/15_learning/basics/04_entity_memory_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import LearningMachine, EntityMemoryConfig, LearningMode
from agno.models.openai import OpenAIResponses

# Setup
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
model = OpenAIResponses(id="gpt-5.2")

# Agent with entity memory
agent = Agent(
    name="Entity Memory Agent",
    model=model,
    db=db,
    learning=LearningMachine(
        db=db,
        model=model,
        user_profile=False,
        entity_memory=EntityMemoryConfig(
            mode=LearningMode.BACKGROUND,  # Auto-extract entities
            namespace="global",  # Shared with everyone
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    user = "entity_demo@example.com"

    # Mention some entities
    agent.print_response(
        "I just had a meeting with Acme Corp. They use PostgreSQL and Redis, "
        "and their CTO Bob mentioned they're launching a new product in Q2.",
        user_id=user,
        session_id="entity_session_1",
        stream=True,
    )

    print("\n---\n")

    # Later, ask about the entity
    agent.print_response(
        "What do we know about Acme Corp?",
        user_id=user,
        session_id="entity_session_2",
        stream=True,
    )
