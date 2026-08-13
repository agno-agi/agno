import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.opensearch import OpenSearch

vector_db = OpenSearch(
    index_name="recipe_async",
)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(knowledge=knowledge_base)


async def main():
    await knowledge_base.add_content_async(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    # Create and use the agent
    await agent.aprint_response("How to make Tom Kha Gai", markdown=True)

    # Release the underlying aiohttp session
    await vector_db.async_close()


if __name__ == "__main__":
    asyncio.run(main())
