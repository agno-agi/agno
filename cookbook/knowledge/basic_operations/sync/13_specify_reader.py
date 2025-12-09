"""This cookbook shows how to specify a reader for reading content.
Readers are assigned by default to the content based on the file extension.
You can specify a reader for a specific content by passing the reader to the add_content method
if you want to use a different reader for a specific content.

1. Run: `python cookbook/agent_concepts/knowledge/13_specify_reader.py` to run the cookbook
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Use a specific reader
knowledge.add_content(
    name="CV",
    path="cookbook/knowledge/testing_resources/cv_1.pdf",
    metadata={"user_tag": "Engineering Candidates"},
    reader=PDFReader(),
)

agent = Agent(knowledge=knowledge)

agent.print_response("What can you tell me about my documents?", markdown=True)
