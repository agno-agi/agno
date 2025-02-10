from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

vector_db = PgVector(table_name="recipes", db_url=db_url)

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)
knowledge_base.load(recreate=False)  # Comment out after first run

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("How to make Thai curry?", markdown=True)
