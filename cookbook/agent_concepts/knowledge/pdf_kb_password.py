from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create a knowledge base with simplified password handling
knowledge_base = PDFUrlKnowledgeBase(
    urls=[
        {
            "url": "https://agno-public.s3.us-east-1.amazonaws.com/recipes/ThaiRecipes_protected.pdf",
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
