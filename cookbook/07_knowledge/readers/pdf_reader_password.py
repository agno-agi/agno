from agno.agent import Agent
from agno.knowledge.content import ContentAuth
from agno.knowledge.knowledge import Knowledge
from agno.utils.media import download_file
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
download_file(
    "https://agno-public.s3.us-east-1.amazonaws.com/recipes/ThaiRecipes_protected.pdf",
    "ThaiRecipes_protected.pdf",
)

# Create a knowledge base with simplified password handling
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="pdf_documents_password",
        db_url=db_url,
    ),
)

knowledge.add_content(
    path="ThaiRecipes_protected.pdf",
    auth=ContentAuth(password="ThaiRecipes"),
)

# Create an agent with the knowledge base
agent = Agent(
    knowledge=knowledge,
    search_knowledge=True,
)

agent.print_response("Give me the recipe for pad thai")
