"""
MMR: Diverse, Non-Redundant Results
===================================
Vector search returns the closest matches to a query, which are often near-duplicates
of each other: five chunks that all say the same thing. MMR (Maximal Marginal
Relevance) picks documents one at a time, discounting each candidate by how similar it
already is to what has been selected.

lambda_mult controls the tradeoff:
- 1.0 ranks by relevance alone (equivalent to plain vector search)
- 0.5 balances relevance against difference
- 0.0 ranks by difference alone

MMR is configured as the vector db's reranker, like any other reranker. Because it
selects a subset, it needs more candidates than the number of results requested.
Knowledge widens the vector db fetch when MMR is set (5x the request, capped at 100),
MMR selects from that pool inside the vector db, and max_results are returned.

MMR reads the embedding on each search result. Not every vector db returns one:
Milvus, MongoDB, Redis and Valkey do not, so MMR raises there rather than silently
returning unreranked results.

Take the returned order as the result: reranking_score holds the MMR score at the
moment each document was picked, which is not descending, so re-sorting by it discards
the diversity ordering.

See also: 03_reranking.py for relevance reranking with Cohere.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.mmr import MMRReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

qdrant_url = "http://localhost:6333"
collection = "mmr_demo"

knowledge = Knowledge(
    vector_db=Qdrant(
        collection=collection,
        url=qdrant_url,
        reranker=MMRReranker(lambda_mult=0.5),
    ),
)

# The same collection without MMR, to compare against.
plain = Knowledge(vector_db=Qdrant(collection=collection, url=qdrant_url))

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    search_knowledge=True,
    markdown=True,
)


def show(results, candidates: int) -> None:
    """Print a snippet per result: every chunk shares the source file name."""
    print(f"Selected {len(results)} of {candidates} candidates:\n")
    for document in results:
        snippet = " ".join(document.content.split())[:100]
        print(f"  - {snippet}...")
    print()


async def main():
    await knowledge.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )

    query = "What are some Thai curry dishes?"
    candidates = len(await plain.asearch(query, max_results=25))

    print("\nWithout MMR")
    show(await plain.asearch(query, max_results=5), candidates)

    # Fetches 25 candidates, selects 5 that are relevant but unlike each other.
    print("With MMR")
    show(await knowledge.asearch(query, max_results=5), candidates)

    await agent.aprint_response("What are some Thai curry dishes?", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
