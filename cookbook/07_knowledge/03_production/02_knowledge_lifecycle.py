"""
Knowledge Lifecycle: Insert, Update, Remove, Track
====================================================
In production, knowledge needs to be managed over time:
- Skip re-inserting content that already exists
- Remove outdated content
- Track content status with a contents database
- Re-index when content changes

This example shows the full content lifecycle with a contents database
for tracking what has been ingested and its current status.

See also: 03_multi_tenant.py for isolating knowledge per tenant.
"""

import asyncio

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    name="Lifecycle Demo",
    vector_db=Qdrant(
        collection="lifecycle_demo",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    # Contents DB tracks ingested content, status, and metadata
    contents_db=SqliteDb(
        db_file="tmp/agent.db",
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        # --- 1. Initial insert ---
        print("\n" + "=" * 60)
        print("STEP 1: Initial insert")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        )
        agent.print_response("What recipes do you know?", stream=True)

        # --- 2. Skip if exists ---
        print("\n" + "=" * 60)
        print("STEP 2: Skip if already exists (no re-processing)")
        print("=" * 60 + "\n")

        await knowledge.ainsert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            skip_if_exists=True,  # Won't re-process since content hash matches
        )
        print("Content was skipped (already exists)")

        # --- 3. Remove content ---
        print("\n" + "=" * 60)
        print("STEP 3: Remove vectors by name")
        print("=" * 60 + "\n")

        await knowledge.aremove_vectors_by_name("Recipes")
        print("Vectors for 'Recipes' removed from the vector database")

    asyncio.run(main())
