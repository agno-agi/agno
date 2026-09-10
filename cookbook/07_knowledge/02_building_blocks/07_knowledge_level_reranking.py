"""
Knowledge-Level Reranking
=========================
A reranker set on Knowledge runs after the vector db returns results, rather than
inside the vector db itself. Two differences follow from that:

1. It works with any vector db, so the same reranker moves between backends.
2. Knowledge widens the fetch first, so the reranker chooses from a real pool.
   Asking for 5 results with a reranker set retrieves rerank_multiplier * 5
   candidates (capped by max_rerank_candidates) and returns the best 5.

The widened fetch is what makes ordering strategies possible: a reranker can only
surface a document that was retrieved in the first place.

A reranker configured on the vector db still runs first. The knowledge-level one
runs on its output.

See also: 03_reranking.py for vector db level reranking.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"

knowledge = Knowledge(
    vector_db=Qdrant(collection="knowledge_reranking_demo", url=qdrant_url),
    # Runs after the vector db returns candidates.
    reranker=CohereReranker(),
    # Retrieve 5x the requested results, so the reranker has candidates to compare.
    rerank_multiplier=5,
    # Ceiling on the widened fetch, whatever max_results is asked for.
    max_rerank_candidates=100,
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)


async def main():
    await knowledge.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    # Retrieves 25 candidates, reranks them, returns the top 5.
    results = await knowledge.asearch("What are some Thai curry dishes?", max_results=5)
    print("Reranked results:")
    for document in results:
        print(f"  {document.name}")

    await agent.aprint_response("What are some Thai curry dishes?", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
