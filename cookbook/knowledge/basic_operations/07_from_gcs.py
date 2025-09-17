"""This cookbook shows how to add content from a GCS bucket to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/07_from_gcs.py` to run the cookbook
"""

import asyncio

from agno.agent import Agent
from agno.db.postgres.postgres import PostgresDb
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.remote_content.remote_content import GCSContent
from agno.vectordb.pgvector import PgVector

contents_db = PostgresDb(
    db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    contents_db=contents_db,
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Add from GCS
asyncio.run(
    knowledge.add_content_async(
        name="GCS PDF",
        remote_content=GCSContent(
            bucket_name="thai-recepies", blob_name="ThaiRecipes.pdf"
        ),
        metadata={"remote_content": "GCS"},
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
    "What is the best way to make a Thai curry?",
    markdown=True,
)
