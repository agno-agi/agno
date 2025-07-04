import asyncio

from agno.agent import Agent
from agno.knowledge.pdf import PDFKnowledgeBase, PDFReader
from agno.vectordb.pgvector import PgVector

# vector_db = Qdrant(collection=COLLECTION_NAME, url="http://localhost:6333")
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


# Create a knowledge base with the PDFs from the data/pdfs directory
knowledge_base = PDFKnowledgeBase(
    path="tmp/manual.pdf",
    vector_db=PgVector(
        table_name="pdf_documents",
        # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
        db_url=db_url,
    ),
    reader=PDFReader(chunk=True),
)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=True))

    # Create and use the agent
    asyncio.run(agent.aprint_response("How to make Thai curry?", markdown=True))
