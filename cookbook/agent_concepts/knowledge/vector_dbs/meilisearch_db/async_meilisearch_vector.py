import asyncio

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

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=False))

    # Create and use the agent
    asyncio.run(agent.aprint_response("How to make Tom Kha Gai", markdown=True))
