"""This cookbook shows how to specify a reader for reading content.
1. Run: `python cookbook/agent_concepts/knowledge/04_specify_reader.py` to run the cookbook
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.pdf_reader import PDFReader
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# Use a specific reader
knowledge.add_content(
    name="CV",
    path="cookbook/agent_concepts/knowledge/testing_resources/",
    metadata={"user_tag": "Engineering Candidates"},
    reader=PDFReader(),
)

agent = Agent(knowledge=knowledge, show_tool_calls=True)

agent.print_response("What can you tell me about my documents?", markdown=True)
