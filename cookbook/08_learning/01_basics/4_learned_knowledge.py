"""
Learned Knowledge: Agentic Mode
===============================
Learned Knowledge stores reusable insights that apply across users:
- Best practices discovered through use
- Domain-specific patterns
- Solutions to common problems

AGENTIC mode gives the agent explicit tools:
- search_learnings: Find relevant past knowledge
- save_learning: Store a new insight

The agent decides when to save and apply learnings.
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

# Learned knowledge requires a vector DB for semantic search.
knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="learned_knowledge_demo",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# AGENTIC mode: Agent gets save/search tools and decides when to use them.
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions="Be concise. Search for relevant learnings before answering questions.",
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
    user_id = "learner@example.com"

    # Session 1: Save a learning
    print("\n" + "=" * 60)
    print("SESSION 1: Save a learning (watch for tool calls)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Save this: Always check cloud egress costs first - they vary 10x between providers.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )
    agent.learning_machine.learned_knowledge_store.print(query="cloud")

    # Session 2: Apply the learning (new user, new session)
    print("\n" + "=" * 60)
    print("SESSION 2: New user asks related question")
    print("=" * 60 + "\n")

    agent.print_response(
        "I'm picking a cloud provider for a 10TB daily data pipeline. Key considerations?",
        user_id="different_user@example.com",
        session_id="session_2",
        stream=True,
    )
