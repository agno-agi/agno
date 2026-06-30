"""
SurrealDB Vector DB
===================

Run SurrealDB before running this example:
`docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root`
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.surrealdb import SurrealDb
from surrealdb import AsyncSurreal, Surreal

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
def create_sync_knowledge() -> Knowledge:
    client = Surreal(url=SURREALDB_URL)
    client.signin({"username": SURREALDB_USER, "password": SURREALDB_PASSWORD})
    client.use(namespace=SURREALDB_NAMESPACE, database=SURREALDB_DATABASE)

    vector_db = SurrealDb(
        client=client,
        collection="recipes",
        efc=150,
        m=12,
        search_ef=40,
        embedder=OpenAIEmbedder(),
    )
    return Knowledge(vector_db=vector_db)


def create_async_knowledge(async_client: AsyncSurreal) -> Knowledge:
    vector_db = SurrealDb(
        async_client=async_client,
        collection="recipes",
        efc=150,
        m=12,
        search_ef=40,
        embedder=OpenAIEmbedder(),
    )
    return Knowledge(vector_db=vector_db)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
def create_agent(knowledge: Knowledge) -> Agent:
    return Agent(knowledge=knowledge)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def run_sync() -> None:
    knowledge = create_sync_knowledge()
    agent = create_agent(knowledge)

    knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")
    agent.print_response(
        "What are the 3 categories of Thai SELECT is given to restaurants overseas?",
        markdown=True,
    )


async def run_async() -> None:
    async_client = AsyncSurreal(url=SURREALDB_URL)
    await async_client.signin(
        {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
    )
    await async_client.use(namespace=SURREALDB_NAMESPACE, database=SURREALDB_DATABASE)

    knowledge = create_async_knowledge(async_client)
    agent = create_agent(knowledge)

    await knowledge.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    await agent.aprint_response(
        "What are the 3 categories of Thai SELECT is given to restaurants overseas?",
        markdown=True,
    )


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
