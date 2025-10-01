"""This cookbook shows how to use batch embeddings with Cohere.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

import asyncio

from agno.agent import Agent  # noqa
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)

vector_db = PgVector(
    table_name="vectors",
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    embedder=CohereEmbedder(
        batch_size=100,
        dimensions=1024,
        exponential_backoff=True,
    ),
)
vector_db.drop()

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=vector_db,
    contents_db=contents_db,
)

asyncio.run(
    knowledge.add_content_async(
        name="CV",
        path="cookbook/knowledge/testing_resources/manual.pdf",
        metadata={"user_tag": "Engineering Candidates"},
    )
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
