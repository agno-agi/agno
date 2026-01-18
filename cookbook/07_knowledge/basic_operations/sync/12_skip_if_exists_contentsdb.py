"""This cookbook shows how to skip content if it already exists in the knowledge base.
It also demonstrates how contents can be added to the contents database post processing when
it is already in the vectorDB.
Existing content is skipped by default.

1. Run: `python cookbook/agent_concepts/knowledge/12_skip_if_exists_contentsdb.py` to run the cookbook
"""

from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)
# Add from a URL to the knowledge base
knowledge.add_content(
    name="CV",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=True,  # True by default
)

# Now add a contents_db to our Knowledge instance
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)
knowledge.contents_db = contents_db

# Add from a URL to the knowledge base that already exists in the vectorDB, but adds it to the contentsDB
knowledge.add_content(
    name="CV",
    url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    skip_if_exists=True,
)
