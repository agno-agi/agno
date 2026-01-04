"""
Learned Knowledge Quick Start
=============================
Capture reusable insights in 50 lines.

Learned Knowledge stores patterns and insights that apply
across users and sessions - collective intelligence.

Run:
    python cookbook/15_learning/basics/05_learned_knowledge_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector, SearchType

# Setup
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIChat(id="gpt-4o")

# Knowledge base for learnings (requires vector DB)
knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="quick_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# Agent with learned knowledge
agent = Agent(
    name="Learning Agent",
    model=model,
    db=db,
    instructions="""\
You learn from conversations and apply prior knowledge.
Use save_learning to store valuable insights.
Use search_learnings to find and apply past learnings.
""",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    user = "learner@example.com"

    # Save a learning
    print("\n--- Save a learning ---\n")
    agent.print_response(
        "Save this insight: When comparing cloud providers, always "
        "check egress costs first - they can vary by 10x.",
        user_id=user,
        session_id="s1",
        stream=True,
    )

    print("\n--- Apply the learning ---\n")
    agent.print_response(
        "Help me choose between AWS and GCP for my new project.",
        user_id=user,
        session_id="s2",
        stream=True,
    )
