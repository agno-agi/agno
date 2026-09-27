import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.elasticsearch import Elasticsearch

vector_db = Elasticsearch(
    index_name="recipe_async",
)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(knowledge=knowledge_base)


async def main():
    await knowledge_base.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    # Create and use the agent
    await agent.aprint_response("How to make Tom Kha Gai", markdown=True)

    # The async client holds an aiohttp session that Python will not close for you:
    # skip this and the script exits with "ResourceWarning: Unclosed connector" and a
    # leaked socket. Closing also covers the sync client, which async-only use still
    # builds for the owner-mapping gate and for search.
    await vector_db.async_close()


if __name__ == "__main__":
    asyncio.run(main())
