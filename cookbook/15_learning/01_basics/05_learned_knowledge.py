"""
Learned Knowledge Quick Start
=============================
Learned Knowledge stores patterns and insights that apply
across users and sessions - collective intelligence:
- Best practices discovered through use
- Domain-specific insights
- Reusable solutions to common problems

This example uses AGENTIC mode with tools, so the agent decides
when to save insights and when to search for relevant knowledge.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Create Agent
# ============================================================================
# Learned knowledge requires a vector DB for semantic search.
# The agent can save insights and search for relevant knowledge.
knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="learned_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    instructions="Learn from conversations and apply prior knowledge.",
    learning=LearningMachine(
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# =============================================================================
# Helper: Show learnings
# =============================================================================
def show_learnings() -> None:
    """Display stored learnings."""
    from rich.pretty import pprint

    store = agent.learning.learned_knowledge_store
    learnings = store.list() if store else []
    pprint(learnings) if learnings else print("\nNo learnings stored yet.")


# ============================================================================
# Demo: Collective Intelligence
# ============================================================================
if __name__ == "__main__":
    user_id = "learner@example.com"

    # Session 1: Save a learning
    print("\n" + "=" * 60)
    print("SESSION 1: Save a learning")
    print("=" * 60 + "\n")
    agent.print_response(
        "Save this insight: When comparing cloud providers, always "
        "check egress costs first - they can vary by 10x.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Learnings ---")
    show_learnings()

    # Session 2: Apply the learning
    print("\n" + "=" * 60)
    print("SESSION 2: Apply learning")
    print("=" * 60 + "\n")
    agent.print_response(
        "Help me choose between AWS and GCP for my new project.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("\n--- Updated Learnings ---")
    show_learnings()
