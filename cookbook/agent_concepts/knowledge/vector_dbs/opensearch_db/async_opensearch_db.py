import asyncio

from agno.agent import Agent
from agno.knowledge.pdf_url import PDFUrlKnowledgeBase
from agno.vectordb.opensearch import OpensearchDb

vector_db = OpensearchDb(
    index_name="recipe",
    dimension=1536,
    hosts=[
        {
            "host": "localhost",
            "port": 9200,
        }
    ],
    # Uncomment the following line to use basic authentication
    # http_auth=("username", "password"),
)

knowledge_base = PDFUrlKnowledgeBase(
    urls=["https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"],
    vector_db=vector_db,
)

agent = Agent(knowledge=knowledge_base, show_tool_calls=True)

if __name__ == "__main__":
    # Comment out after first run
    asyncio.run(knowledge_base.aload(recreate=True))
    # Create and use the agent
    asyncio.run(agent.aprint_response("How to make Tom Kha Gai", markdown=True))
