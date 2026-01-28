"""
Support Agent
=============
A customer support agent with learning capabilities.

The agent learns from successful resolutions and applies them to future tickets.

Requirements:
    - PostgreSQL with PgVector running (./cookbook/scripts/run_pgvector.sh)
    - Knowledge base loaded (./scripts/load_knowledge.py)

See also: examples/learning_demo.py for the full demo.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    EntityMemoryConfig,
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"

db = PostgresDb(db_url=DB_URL)

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="support_knowledge",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


def create_support_agent(customer_id: str, ticket_id: str) -> Agent:
    """Create a support agent for a specific ticket."""
    return Agent(
        model=OpenAIResponses(id="gpt-4.1"),
        db=db,
        instructions=(
            "You are a helpful support agent. "
            "Check if similar issues have been solved before. "
            "Save successful solutions for future reference."
        ),
        learning=LearningMachine(
            knowledge=knowledge,
            session_context=SessionContextConfig(enable_planning=True),
            entity_memory=EntityMemoryConfig(
                mode=LearningMode.ALWAYS,
                namespace="support",
            ),
            learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
        ),
        user_id=customer_id,
        session_id=ticket_id,
        search_knowledge=True,
        markdown=True,
    )


# ============================================================================
# Demo
# ============================================================================

if __name__ == "__main__":
    agent = create_support_agent("demo@example.com", "demo_ticket")
    agent.print_response(
        "What are the SLA response times for different priority levels?",
        stream=True,
    )
