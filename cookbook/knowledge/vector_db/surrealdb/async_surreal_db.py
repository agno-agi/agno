# Run SurrealDB in a container before running this script
# docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.surrealdb import SurrealDb
from surrealdb import AsyncSurreal

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"

# Create a client
client = AsyncSurreal(url=SURREALDB_URL)

surrealdb = SurrealDb(
    async_client=client,
    collection="recipes",  # Collection name for storing documents
    efc=150,  # HNSW construction time/accuracy trade-off
    m=12,  # HNSW max number of connections per element
    search_ef=40,  # HNSW search time/accuracy trade-off
    embedder=OpenAIEmbedder(),
)


async def async_demo():
    """Demonstrate asynchronous usage of SurrealDb"""

    await client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
    await client.use(namespace=SURREALDB_NAMESPACE, database=SURREALDB_DATABASE)

    knowledge = Knowledge(
        vector_db=surrealdb,
    )

    await knowledge.add_content_async(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
    )

    agent = Agent(knowledge=knowledge)
    await agent.aprint_response(
        "What are the 3 categories of Thai SELECT is given to restaurants overseas?",
        markdown=True,
    )


if __name__ == "__main__":
    # Run asynchronous demo
    print("\nRunning asynchronous demo...")
    asyncio.run(async_demo())
