"""
Valkey Vector DB
===============

Demonstrates Valkey-backed knowledge with sync and async flows.

To get started, start local Valkey with:
`docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle`

Install dependency:
`uv pip install valkey-glide-sync pypdf`
"""

import asyncio
import os

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.search import SearchType
from agno.vectordb.valkey import ValkeyVectorDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
INDEX_NAME = os.getenv("VALKEY_INDEX", "agno_cookbook_vectors")

vector_db = ValkeyVectorDb(
    index_name=INDEX_NAME,
    search_type=SearchType.vector,
)


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
knowledge = Knowledge(
    name="My Valkey Vector Knowledge Base",
    description="This knowledge base uses Valkey as the vector store",
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
