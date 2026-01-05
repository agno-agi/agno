"""
Learned Knowledge: Agentic Mode
===============================
Learned Knowledge stores patterns and insights that apply
across users and sessions - collective intelligence:
- Best practices discovered through use
- Domain-specific insights
- Reusable solutions to common problems

AGENTIC mode gives the agent explicit tools:
- save_learning: Store a new insight
- search_learnings: Find relevant past knowledge

The agent decides when to save and apply learnings.

Compare with: 05a_learned_knowledge_background.py for automatic extraction.
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
# AGENTIC mode gives the agent save/search tools.
knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="learned_knowledge_ag",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    instructions="Learn from conversations and apply prior knowledge. "
    "Save valuable insights for future use.",
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
    learnings = store.search(query="", limit=10) if store else []
    pprint(learnings) if learnings else print("\nNo learnings stored yet.")


# ============================================================================
# Demo: Explicit Knowledge Management
# ============================================================================
if __name__ == "__main__":
    user_id = "learner_ag@example.com"

    # Session 1: Explicitly save a learning
    print("\n" + "=" * 60)
    print("SESSION 1: Save a learning (watch for tool calls)")
    print("=" * 60 + "\n")
    agent.print_response(
        "Save this insight: When comparing cloud providers, always "
        "check egress costs first - they can vary by 10x and often "
        "dominate total costs for data-intensive workloads.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Learnings ---")
    show_learnings()

    # Session 2: Apply the learning
    print("\n" + "=" * 60)
    print("SESSION 2: Apply learning to new question")
    print("=" * 60 + "\n")
    agent.print_response(
        "I'm choosing between AWS and GCP for a data pipeline that "
        "processes 10TB daily. What should I consider?",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    print("\n--- Learnings ---")
    show_learnings()

    # Session 3: Add another learning
    print("\n" + "=" * 60)
    print("SESSION 3: Save another insight")
    print("=" * 60 + "\n")
    agent.print_response(
        "Good point about egress! I also learned that reserved instances "
        "can save 40-60% but require 1-3 year commitments. Worth noting "
        "for future cloud cost discussions.",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    print("\n--- Updated Learnings ---")
    show_learnings()

    # Session 4: Different user benefits
    print("\n" + "=" * 60)
    print("SESSION 4: Different user, collective knowledge")
    print("=" * 60 + "\n")
    agent.print_response(
        "What are the key things to evaluate when choosing a cloud provider?",
        user_id="other@example.com",  # Different user
        session_id="session_4",
        stream=True,
    )
    print("\n--- Final Learnings ---")
    show_learnings()
