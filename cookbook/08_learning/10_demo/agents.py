"""
Learning Demo: Shared Agent
===========================
A single ops assistant with every learning store enabled:

- User Profile: structured fields (name, role, preferences)
- User Memory: unstructured observations about the user
- Session Context: goal, plan, and progress per session
- Entity Memory: facts, events, and relationships about external things
- Learned Knowledge: insights that transfer across users (pgvector)
- Decision Log: significant decisions with reasoning

Requires the pgvector container:
    ./cookbook/scripts/run_pgvector.sh
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    DecisionLogConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
)
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(id="learning-demo-db", db_url=db_url)

# Learned Knowledge needs a vector store for semantic search.
knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="learning_demo_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Learning Machine: all six stores enabled
# ---------------------------------------------------------------------------
learning = LearningMachine(
    db=db,
    model=OpenAIResponses(id="gpt-5.5"),
    knowledge=knowledge,
    user_profile=True,
    user_memory=True,
    session_context=SessionContextConfig(enable_planning=True),
    entity_memory=True,
    learned_knowledge=True,
    decision_log=DecisionLogConfig(mode=LearningMode.AGENTIC),
)

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
ops_assistant = Agent(
    id="ops-assistant",
    name="Ops Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=learning,
    instructions=[
        "You are an engineering operations assistant.",
        "Keep answers short and practical.",
        "Search your learnings before answering substantive questions.",
        "When the user shares a team-wide insight or asks you to remember one, save it with the save_learning tool.",
        "When you make a significant recommendation, record it with the log_decision tool, including your reasoning and the alternatives you considered.",
    ],
    markdown=True,
)
