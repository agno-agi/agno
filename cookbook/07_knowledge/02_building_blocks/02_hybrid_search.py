"""
Search Types: Vector, Keyword, and Hybrid
===========================================
Knowledge supports three search types. Each has different strengths:

- Vector: Semantic similarity search. Finds conceptually related content
  even when exact words don't match.
- Keyword: Full-text search. Fast and precise for exact term matching.
- Hybrid: Combines vector + keyword. Best of both worlds. Recommended default.

See also: 03_reranking.py for improving search results with reranking.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"
pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"


def create_knowledge(search_type: SearchType) -> Knowledge:
    return Knowledge(
        vector_db=Qdrant(
            collection="search_types_%s" % search_type.value,
            url=qdrant_url,
            search_type=search_type,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    async def main():
        search_types = [
            (SearchType.vector, "Vector (semantic similarity)"),
            (SearchType.keyword, "Keyword (full-text search)"),
            (SearchType.hybrid, "Hybrid (vector + keyword)"),
        ]

        for search_type, description in search_types:
            print("\n" + "=" * 60)
            print("SEARCH TYPE: %s" % description)
            print("=" * 60 + "\n")

            knowledge = create_knowledge(search_type)
            # skip_if_exists=True avoids re-processing if run multiple times
            await knowledge.ainsert(url=pdf_url, skip_if_exists=True)

            agent = Agent(
                model=OpenAIResponses(id="gpt-5.2"),
                knowledge=knowledge,
                search_knowledge=True,
                markdown=True,
            )
            agent.print_response(
                "How do I make pad thai?",
                stream=True,
            )

    asyncio.run(main())
