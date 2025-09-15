"""This cookbook shows how to remove content from Knowledge when using a ContentDB.

You can remove content by id or by name.

1. Run: `python cookbook/agent_concepts/knowledge/09_remove_content.py` to run the cookbook
"""

import asyncio

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
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

asyncio.run(
    knowledge.add_content_async(
        name="CV",
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
    )
)


# Remove content and vectors by id
contents, _ = knowledge.get_content()
for content in contents:
    print(content.id)
    print(" ")
    knowledge.remove_content_by_id(content.id)

# Remove all content
knowledge.remove_all_content()
