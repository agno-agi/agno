"""
Learned Knowledge
===========================================
Learned knowledge stores reusable insights that apply across ALL users.

Think of it as:
- User Profile = what you know about a specific person
- Session Context = what's happening in this conversation
- Learned Knowledge = insights that help with any similar question

The agent gets TWO tools:
- search_learnings: Find relevant prior insights (semantic search)
- save_learning: Store a new reusable insight

Learnings are SHARED — an insight from user A helps user B.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import LearningMachine
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Knowledge base for storing learnings (uses vector embeddings for search)
knowledge = AgentKnowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agent_learnings",
    ),
)

# =============================================================================
# Create Learning Agent with Knowledge Base
# =============================================================================
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,  # This auto-enables LearnedKnowledgeStore!
        user_profile=True,
    ),
    markdown=True,
)


# =============================================================================
# Helper: Search learnings
# =============================================================================
def search_learnings(query: str, limit: int = 3):
    """Search the knowledge base for relevant learnings."""
    results = agent.learning.stores["learned_knowledge"].search(query=query, limit=limit)
    if results:
        print(f"\n🔍 Found {len(results)} learning(s) for '{query}':")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            learning = getattr(r, 'learning', str(r))[:80]
            print(f"   > {title}: {learning}...")
    else:
        print(f"\n🔍 No learnings found for '{query}'")
    print()


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    # --- Conversation 1: Agent discovers a pattern ---
    print("=" * 60)
    print("Conversation 1: Agent discovers an insight")
    print("=" * 60)
    agent.print_response(
        "I'm trying to optimize my PostgreSQL queries. They're running slow "
        "on a table with 10 million rows. I'm filtering by created_at.",
        user_id="eve@example.com",
        session_id="session_1",
        stream=True,
    )
    search_learnings("postgresql optimization")

    # --- Conversation 2: Different user, related question ---
    print("=" * 60)
    print("Conversation 2: Different user benefits from learning")
    print("=" * 60)
    agent.print_response(
        "My database queries are slow. I have a large orders table "
        "and I'm querying by date ranges. Any tips?",
        user_id="frank@example.com",  # Different user!
        session_id="session_2",
        stream=True,
    )

    # --- Conversation 3: Another user, same topic ---
    print("=" * 60)
    print("Conversation 3: Learnings compound over time")
    print("=" * 60)
    agent.print_response(
        "How do I make time-based queries faster in Postgres?",
        user_id="grace@example.com",  # Yet another user
        session_id="session_3",
        stream=True,
    )

    # --- Show accumulated learnings ---
    print("=" * 60)
    print("Accumulated Learnings")
    print("=" * 60)
    search_learnings("database performance")
    search_learnings("index optimization")
