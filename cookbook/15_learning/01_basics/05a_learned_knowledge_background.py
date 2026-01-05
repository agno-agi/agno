"""
Learned Knowledge: Background Mode
==================================
Learned Knowledge stores patterns and insights that apply
across users and sessions - collective intelligence:
- Best practices discovered through use
- Domain-specific insights
- Reusable solutions to common problems

BACKGROUND mode automatically extracts learnings from conversations.
Insights are captured without explicit tool calls.

Compare with: 05b_learned_knowledge_agentic.py for explicit tool-based saving.
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
# BACKGROUND mode extracts insights automatically after responses.
knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="learned_knowledge_bg",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"),
    learning=LearningMachine(
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.BACKGROUND,
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
# Demo: Automatic Knowledge Extraction
# ============================================================================
if __name__ == "__main__":
    user_id = "learner_bg@example.com"

    # Session 1: Problem-solving that generates insights
    print("\n" + "=" * 60)
    print("SESSION 1: Solve a problem (learnings extracted automatically)")
    print("=" * 60 + "\n")
    agent.print_response(
        "I'm debugging a slow PostgreSQL query. It's doing a sequential scan "
        "on a table with 10M rows. How should I approach this?",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    print("\n--- Stored Learnings ---")
    show_learnings()

    # Session 2: Another user benefits from the learning
    print("\n" + "=" * 60)
    print("SESSION 2: Different user, similar problem")
    print("=" * 60 + "\n")
    agent.print_response(
        "My database queries are running slowly. Any general tips?",
        user_id="other_user@example.com",  # Different user
        session_id="session_2",
        stream=True,
    )
    print("\n--- Learnings Applied ---")
    show_learnings()

    # Session 3: More complex scenario
    print("\n" + "=" * 60)
    print("SESSION 3: Build on existing knowledge")
    print("=" * 60 + "\n")
    agent.print_response(
        "I added an index but the query is still slow. The EXPLAIN shows "
        "it's not using my index. What could be wrong?",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
    print("\n--- Final Learnings ---")
    show_learnings()
