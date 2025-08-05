from agno.agent import Agent
from agno.knowledge.pdf import PDFKnowledgeBase, PDFReader
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with the PDFs from the data/pdfs directory
knowledge_base = PDFKnowledgeBase(
    path="tmp/ThaiRecipes_protected.pdf",
    vector_db=PgVector(
        table_name="pdf_documents_password",
        db_url=db_url,
    ),
    reader=PDFReader(chunk=True, password="ThaiRecipes"),
)
# Load the knowledge base
knowledge_base.load(recreate=True)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge_base,
    search_knowledge=True,
    show_tool_calls=True,
)

agent.print_response("Give me the recipe for pad thai")
