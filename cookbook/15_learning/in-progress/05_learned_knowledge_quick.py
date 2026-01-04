"""
Learned Knowledge Quick Start
=============================
Reusable insights in 30 lines.

Learned Knowledge captures insights and patterns that can be:
- Searched semantically (via vector embeddings)
- Shared across users (global namespace)
- Kept private (user namespace)
- Scoped to teams (custom namespace)

Requires a Knowledge base (vector database) for semantic search.

Run:
    python cookbook/15_learning/basics/05_learned_knowledge_quick.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# Setup
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")

# Knowledge base for storing learnings (required for semantic search)
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
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,  # Agent decides when to save
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

# Demo
if __name__ == "__main__":
    user = "learner@example.com"

    # Agent learns something valuable
    agent.print_response(
        "I discovered that when comparing cloud providers, you should always "
        "check egress costs first - they vary wildly and can dominate the bill. "
        "Please save this as a learning.",
        user_id=user,
        session_id="learn_session_1",
        stream=True,
    )

    print("\n---\n")

    # Later, agent can search and apply prior learnings
    agent.print_response(
        "Help me compare AWS vs GCP for my project.",
        user_id=user,
        session_id="learn_session_2",
        stream=True,
    )
