"""This cookbook shows how to add content from a local file to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    contents_db=PostgresDb(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        knowledge_table="knowledge_contents",
    ),
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

knowledge.add_content(
    name="CV",
    path="cookbook/agent_concepts/knowledge/testing_resources/",
    metadata={"user_tag": "Engineering Candidates"},
)


# Remove content and vectors by id
contents, _ = knowledge.get_content()
for content in contents:
    print(content.id)
    print(" ")
    knowledge.remove_content_by_id(content.id)

# Remove all content
knowledge.remove_all_content()
