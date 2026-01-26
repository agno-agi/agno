"""This cookbook shows how to use batch embeddings with OpenAI.
1. Run: `python cookbook/07_knowledge/basic_operations/async/15_batching.py` to run the cookbook
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.lancedb import LanceDb

vector_db = LanceDb(
    uri="tmp/lancedb",
    table_name="vectors",
    embedder=OpenAIEmbedder(
        batch_size=1000,
        dimensions=1536,
        enable_batch=True,
    ),
)

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=vector_db,
)


asyncio.run(
    knowledge.ainsert(
        name="CV",
        path="cookbook/07_knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
    )
)

agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    debug_mode=True,
)

agent.print_response(
    "What skills does Jordan Mitchell have?",
    markdown=True,
)
