from agno.agent import Agent
from agno.knowledge.pdf import PDFKnowledgeBase, PDFReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the PDFs from the data/pdfs directory
knowledge_base = PDFKnowledgeBase(
    path=[
        {
            "path": "tmp/cv_2.pdf",
            "metadata": {
                "user_tag": "Engineering candidates"
            }
        }],
    vector_db=PgVector(
        table_name="vectors",
        # Can inspect database via psql e.g. "psql -h localhost -p 5432 -U ai -d ai"
        db_url=db_url,
    ),
    reader=PDFReader(chunk=True, chunk_size=100),
)
# Load the knowledge base
knowledge_base.load(recreate=False)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    debug_mode=True,
)

# Ask the agent about the knowledge base
agent.print_response("Who is the best engineering candidate? Search the knowledge base for the answer.", markdown=True)
