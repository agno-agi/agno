"""This cookbook shows how to add content from a local file to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

from agno.agent import Agent  # noqa
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

vector_db = PgVector(
    table_name="vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=vector_db,
    contents_db=contents_db,
)

knowledge.add_content(
    name="CV",
    path="cookbook/knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
)

agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response(
    "What skills does Jordan Mitchell have?",
    markdown=True,
)
