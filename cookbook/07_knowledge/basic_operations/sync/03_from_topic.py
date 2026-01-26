"""This cookbook shows how to add topics from Wikipedia and Arxiv to the knowledge base.

It is important to specify the reader for the content when using topics.

1. Run: `pip install agno wikipedia arxiv` to install the dependencies
2. Run: `python cookbook/07_knowledge/basic_operations/sync/03_from_topic.py` to run the cookbook
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
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
    contents_db=PostgresDb(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        knowledge_table="knowledge_contents",
    ),
)

# Add topics from Wikipedia
knowledge.insert(
    metadata={"user_tag": "Wikipedia content"},
    topics=["Manchester United"],
    reader=WikipediaReader(),
)

# Add topics from Arxiv
knowledge.insert(
    metadata={"user_tag": "Arxiv content"},
    topics=["Carbon Dioxide", "Oxygen"],
    reader=ArxivReader(),
)

# Using the insert_many method
knowledge.insert_many(
    topics=["Carbon Dioxide", "Nitrogen"],
    reader=ArxivReader(),
    skip_if_exists=True,
)

agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response(
    "What can you tell me about Manchester United?",
    markdown=True,
)
