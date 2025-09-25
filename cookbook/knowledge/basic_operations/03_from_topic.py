"""This cookbook shows how to add topics from Wikipedia and Arxiv to the knowledge base.

It is important to specify the reader for the content when using topics.

1. Run: `pip install agno wikipedia arxiv` to install the dependencies
2. Run: `python cookbook/agent_concepts/knowledge/03_from_topic.py` to run the cookbook
"""

import asyncio

from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.arxiv_reader import ArxivReader
from agno.knowledge.reader.wikipedia_reader import WikipediaReader
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Add topics from Wikipedia
asyncio.run(
    knowledge.add_content_async(
        metadata={"user_tag": "Wikipedia content"},
        topics=["Manchester United"],
        reader=WikipediaReader(),
    )
)

# Add topics from Arxiv
asyncio.run(
    knowledge.add_content_async(
        metadata={"user_tag": "Arxiv content"},
        topics=["Carbon Dioxide", "Oxygen"],
        reader=ArxivReader(),
    )
)

# Using the add_contents method
asyncio.run(
    knowledge.add_contents_async(
        topics=["Carbon Dioxide", "Nitrogen"],
        reader=ArxivReader(),
    )
)
