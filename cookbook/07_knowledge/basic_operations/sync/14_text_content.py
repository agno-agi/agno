"""This cookbook shows how to add text content directly to the knowledge base.

Use `text_content` for single strings or `text_contents` for multiple strings.
This is useful when you have text that doesn't come from a file.

1. Run: `python cookbook/07_knowledge/basic_operations/sync/14_text_content.py` to run the cookbook
"""

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

# Add a single piece of text content
knowledge.insert(
    name="Text Content",
    text_content="Cats and dogs are pets.",
    metadata={"user_tag": "Animals"},
)

# Add multiple pieces of text content
knowledge.insert_many(
    name="Text Content",
    text_contents=["Cats and dogs are pets.", "Birds and fish are not pets."],
    metadata={"user_tag": "Animals"},
)

# OR
knowledge.insert_many(
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
