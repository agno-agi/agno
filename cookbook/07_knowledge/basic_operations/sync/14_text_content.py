"""This cookbook shows how to add content from a local file to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
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
knowledge.add_content(
    name="Text Content",
    text_content="Cats and dogs are pets.",
    metadata={"user_tag": "Animals"},
)

# Add multiple pieces of text content
knowledge.add_contents(
    name="Text Content",
    text_contents=["Cats and dogs are pets.", "Birds and fish are not pets."],
    metadata={"user_tag": "Animals"},
)

# OR
knowledge.add_contents(
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
