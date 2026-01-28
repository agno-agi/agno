"""This cookbook shows how to remove content from Knowledge when using a ContentDB.

You can remove content by id or by name.

1. Run: `python cookbook/07_knowledge/basic_operations/async/09_remove_content.py` to run the cookbook
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


async def main():
    await knowledge.ainsert(
        name="CV",
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
    )

    # Remove content and vectors by id
    contents, _ = await knowledge.aget_content()
    for content in contents:
        print(content.id)
        print(" ")
        await knowledge.aremove_content_by_id(content.id)

    # Remove all content
    await knowledge.aremove_all_content()


asyncio.run(main())
