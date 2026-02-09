"""
Learned Knowledge: Agentic Mode (Deep Dive)
===========================================
Agent decides when to save and retrieve learnings.

AGENTIC mode gives the agent tools:
- save_learning: Store reusable insights
- search_learnings: Find relevant prior knowledge

The agent decides what's worth remembering.

Compare with: 02_propose_mode.py for human-reviewed learnings.
See also: 01_basics/4_learned_knowledge.py for the basics.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="agentic_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions=(
        "You learn from interactions. "
        "Use save_learning to store valuable, reusable insights. "
        "Use search_learnings to find and apply prior knowledge."
    ),
    learning=LearningMachine(
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "learn@example.com"

    # Save a learning
    print("\n" + "=" * 60)
    print("MESSAGE 1: Save a learning")
    print("=" * 60 + "\n")

    agent.print_response(
        "Save this insight: When comparing cloud providers, always check "
        "egress costs first - they can vary by 10x between providers.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    agent.learning_machine.learned_knowledge_store.print(query="cloud egress")

    # Save another learning
    print("\n" + "=" * 60)
    print("MESSAGE 2: Save another learning")
    print("=" * 60 + "\n")

    agent.print_response(
        "Save this: For database migrations, always test rollback "
        "procedures in staging before running in production.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    agent.learning_machine.learned_knowledge_store.print(query="database migration")

    # Apply learnings
    print("\n" + "=" * 60)
    print("MESSAGE 3: Apply learnings to new question")
    print("=" * 60 + "\n")

    agent.print_response(
        "I'm setting up a new project with PostgreSQL on AWS. "
        "What best practices should I follow?",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
