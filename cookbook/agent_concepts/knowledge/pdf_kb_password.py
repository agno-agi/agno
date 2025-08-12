from agno.agent import Agent
from agno.knowledge.pdf import PDFKnowledgeBase
from agno.utils.media import download_file
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
download_file(
    "https://agno-public.s3.us-east-1.amazonaws.com/recipes/ThaiRecipes_protected.pdf",
    "ThaiRecipes_protected.pdf",
)

# Create a knowledge base with simplified password handling
knowledge_base = PDFKnowledgeBase(
    path=[
        {
            "path": "ThaiRecipes_protected.pdf",
            "password": "ThaiRecipes",
        }
    ],
    vector_db=PgVector(
        table_name="pdf_documents_password",
        db_url=db_url,
    ),
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
