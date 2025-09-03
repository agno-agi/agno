from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.meilisearch import MeiliSearch

vector_db = MeiliSearch(
    index_name="recipes",
    url="http://localhost:7700",
    api_key="your-api-key",  # Optional
    wait_check_task=True,
)

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)
knowledge_base.load(recreate=False)  # Comment out after first run

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)
agent.print_response("How to make Thai curry?", markdown=True)
