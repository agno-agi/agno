from agno.agent import Agent
from agno.knowledge.pdf import PDFKnowledgeBase, PDFReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the PDFs from the data/pdfs directory
knowledge_base = PDFKnowledgeBase(
    path="data/pdfs",
    vector_db=PgVector(
        table_name="pdf_documents",
        # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
        db_url=db_url,
    ),
    reader=PDFReader(chunk=True),
)
# Load the knowledge base
knowledge_base.load(recreate=False)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
)

# Ask the agent about the knowledge base
agent.print_response("Ask me about something from the knowledge base", markdown=True)
