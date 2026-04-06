"""
Team Learning: Learned Knowledge
=================================
Teams can build a shared knowledge base from conversations using
LearnedKnowledge with a vector database.

The team uses tools to:
- save_learning: Store reusable insights, best practices, and lessons
- search_learnings: Find and apply prior knowledge to new questions

This is useful for teams that accumulate institutional knowledge
like engineering best practices, incident learnings, or design patterns.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
)
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="team_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
sre_engineer = Agent(
    name="SRE Engineer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Provide guidance on reliability, monitoring, and incident response.",
)

platform_engineer = Agent(
    name="Platform Engineer",
    model=OpenAIResponses(id="gpt-5.2"),
    role="Advise on infrastructure, scaling, and platform architecture.",
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Platform Team",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[sre_engineer, platform_engineer],
    db=db,
    learning=LearningMachine(
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
        ),
    ),
    markdown=True,
    show_members_responses=True,
)


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    user_id = "erik@example.com"

    # Session 1: Save a learning from an incident
    print("\n" + "=" * 60)
    print("SESSION 1: Save learnings from a recent incident")
    print("=" * 60 + "\n")

    team.print_response(
        "We just had a production incident: our database connection pool "
        "was exhausted because a new microservice opened too many connections. "
        "Save the key learnings from this - we should always use connection "
        "pooling with PgBouncer and set max_connections per service.",
        user_id=user_id,
        session_id="session_1",
        stream=True,
    )

    lm = team.learning_machine
    print("\n--- Stored Learnings ---")
    lm.learned_knowledge_store.print(query="connection pool")

    # Session 2: Save another learning
    print("\n" + "=" * 60)
    print("SESSION 2: Save another learning")
    print("=" * 60 + "\n")

    team.print_response(
        "Save this best practice: when deploying to Kubernetes, always set "
        "resource requests and limits. Without them, pods can starve other "
        "workloads or get OOM killed unexpectedly.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    print("\n--- Stored Learnings ---")
    lm.learned_knowledge_store.print(query="kubernetes")

    # Session 3: Apply learnings to a new question
    print("\n" + "=" * 60)
    print("SESSION 3: Apply learnings to a new situation")
    print("=" * 60 + "\n")

    team.print_response(
        "We're launching a new microservice that connects to PostgreSQL "
        "and runs on Kubernetes. What should we watch out for?",
        user_id=user_id,
        session_id="session_3",
        stream=True,
    )
