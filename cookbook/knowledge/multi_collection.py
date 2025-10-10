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

vector_db1 = PgVector(
    table_name="vectors1", # If no name is provided, the table name is used
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

vector_db2 = PgVector(
    name="My Vector Collection",
    table_name="vectors2",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    # vector_db=vector_db,  - Still accepted DX

    vector_dbs=[vector_db1, vector_db2],
    contents_db=contents_db,
)

knowledge.add_content(
    name="CV",
    path="cookbook/knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    vdb_name="vectors1",
    skip_if_exists=True,
)


knowledge.add_content(
    name="CV2",
    path="cookbook/knowledge/testing_resources/cv_2.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    vdb_name="My Vector Collection",
    skip_if_exists=True,
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
