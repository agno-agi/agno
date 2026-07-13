"""
Error Handling: Production Patterns
=====================================
Production knowledge systems need to handle failures gracefully:
- Content that fails to load
- Vector DB connection issues
- Large document batches with partial failures

This example shows patterns for robust knowledge ingestion.
"""

import asyncio
import logging

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection="error_handling_demo",
        url=qdrant_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
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
        # --- 1. Safe insert with skip_if_exists ---
        print("\n" + "=" * 60)
        print("PATTERN 1: Idempotent inserts with skip_if_exists")
        print("=" * 60 + "\n")

        # Safe to call multiple times - won't re-process existing content
        await knowledge.ainsert(
            name="Recipes",
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            skip_if_exists=True,
        )
        print("Insert completed (skipped if already exists)")

        # --- 2. Batch with mixed valid/invalid sources ---
        print("\n" + "=" * 60)
        print("PATTERN 2: Batch insert with error logging")
        print("=" * 60 + "\n")

        sources = [
            {"name": "Valid", "text_content": "This will succeed."},
            {"name": "Also Valid", "text_content": "This will also succeed."},
        ]

        for source in sources:
            try:
                await knowledge.ainsert(**source)
                print("Inserted: %s" % source["name"])
            except Exception as e:
                logger.error("Failed to insert %s: %s", source["name"], e)

        # --- 3. Verify knowledge is usable ---
        print("\n" + "=" * 60)
        print("PATTERN 3: Verify knowledge after ingestion")
        print("=" * 60 + "\n")

        agent.print_response("What do you know?", stream=True)

    asyncio.run(main())
