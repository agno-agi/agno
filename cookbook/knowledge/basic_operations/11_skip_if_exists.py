"""This cookbook shows how to skip content if it already exists in the knowledge base.
Existing content is skipped by default.

1. Run: `python cookbook/agent_concepts/knowledge/11_skip_if_exists.py` to run the cookbook
"""

import asyncio

from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Add from local file to the knowledge base
asyncio.run(
    knowledge.add_content_async(
        name="CV",
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
        skip_if_exists=True,  # True by default
    )
)

# Add from local file to the knowledge base, but don't skip if it already exists
asyncio.run(
    knowledge.add_content_async(
        name="CV",
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
        metadata={"user_tag": "Engineering Candidates"},
        skip_if_exists=False,
    )
)
