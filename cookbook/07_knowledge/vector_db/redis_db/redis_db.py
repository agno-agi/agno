"""
Redis Vector DB
===============

Demonstrates Redis-backed knowledge with sync and async flows.

To get started, either set `REDIS_URL`, or start local Redis with:
`./cookbook/scripts/run_redis.sh`
"""

import asyncio
import os

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.redis import RedisVectorDb
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
INDEX_NAME = os.getenv("REDIS_INDEX", "agno_cookbook_vectors")

vector_db = RedisVectorDb(
    index_name=INDEX_NAME,
    redis_url=REDIS_URL,
    search_type=SearchType.vector,
)


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    name="My Redis Vector Knowledge Base",
    description="This knowledge base uses Redis + RedisVL as the vector store",
    vector_db=vector_db,
)


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(knowledge=knowledge)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def run_sync() -> None:
    knowledge.insert(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book"},
        skip_if_exists=True,
    )
    agent.print_response(
        "List down the ingredients to make Massaman Gai", markdown=True
    )


async def run_async() -> None:
    await knowledge.ainsert(
        name="Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"doc_type": "recipe_book"},
        skip_if_exists=True,
    )
    await agent.aprint_response(
        "List down the ingredients to make Massaman Gai", markdown=True
    )


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
