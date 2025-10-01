"""This cookbook shows how to use batch embeddings with Cohere.
1. Run: `python cookbook/agent_concepts/knowledge/01_from_path.py` to run the cookbook
"""

import asyncio

from agno.agent import Agent  # noqa
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

vector_db = LanceDb(
    uri="tmp/lancedb",  # You can change this path to store data elsewhere
    table_name="vectors",
    embedder=OpenAIEmbedder(
        batch_size=1000,
        dimensions=1536,
        enable_batch=True,
    ),
)
contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
    knowledge_table="knowledge_contents",
)


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
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
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
