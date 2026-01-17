"""This cookbook shows how to add text content directly to the knowledge base (async).

Use `text_content` for single strings or `text_contents` for multiple strings.
This is useful when you have text that doesn't come from a file.

1. Run: `python cookbook/08_knowledge/basic_operations/async/14_text_content.py`
"""

import asyncio

from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

vector_db = PgVector(
    table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
)
# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=vector_db,
    contents_db=contents_db,
)


async def main():
    # Add a single piece of text content
    await knowledge.ainsert(
        name="Text Content",
        text_content="Cats and dogs are pets.",
        metadata={"user_tag": "Animals"},
    )

    # Add multiple pieces of text content
    await knowledge.ainsert_many(
        name="Text Content",
        text_contents=["Cats and dogs are pets.", "Birds and fish are not pets."],
        metadata={"user_tag": "Animals"},
    )

    # OR
    await knowledge.ainsert_many(
        [
            {
                "text_content": "Cats and dogs are pets.",
                "metadata": {"user_tag": "Animals"},
            },
            {
                "text_content": "Birds and fish are not pets.",
                "metadata": {"user_tag": "Animals"},
            },
        ],
    )


asyncio.run(main())
