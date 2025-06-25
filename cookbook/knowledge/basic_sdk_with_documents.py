from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector
from agno.agent import Agent
from typing import List, Optional
from agno.document.reader import Reader
from agno.document.document_v2 import DocumentV2
from agno.knowledge.pdf import PDFReader
from agno.document.reader.csv_reader import CSVReader


# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base", 
    description="Agno 2.0 Knowledge Implementation",
    vector_store=PgVector(
        table_name="vectors",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
    # vvv This is allowed, but we won't encourage this in our cookbooks. vvv
    documents=[
        DocumentV2(
            name="CV2",
            paths="tmp/",
            metadata={"user_tag": "Engineering candidates"},
            reader=PDFReader(),
        )
    ]
)

# Load the knowledge base
knowledge.load()

agent = Agent(
    name="My Agent",
    description="Agno 2.0 Agent Implementation",
    knowledge=knowledge,
    search_knowledge=True,
    debug_mode=True,
)

agent.print_response("Who is the best engineering candidate? Search the knowledge base for the answer.", markdown=True)