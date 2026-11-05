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

MMR needs a pool larger than the number of results requested, which is what the
reranker provides: candidate_multiplier widens the fetch, MMR selects from it, and
max_results are returned.

MMR reads the embedding on each search result. Not every vector db returns one:
Milvus, MongoDB, Redis and Valkey do not, so MMR raises there rather
than silently returning unreranked results.

Take the returned order as the result: reranking_score holds the MMR score at the
moment each document was picked, which is not descending, so re-sorting by it discards
the diversity ordering.

Set a reranker in one place: with one on both Knowledge and the vector db, only the
one on Knowledge is applied and the vector db's is ignored.

See also: 07_knowledge_level_reranking.py for how the widened fetch works.
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

knowledge = Knowledge(
    vector_db=Qdrant(collection="mmr_demo", url=qdrant_url),
    reranker=MMRReranker(
        # Relevance against diversity: 1.0 is relevance alone, 0.0 difference alone.
        lambda_mult=0.5,
        # Candidates fetched per requested result, so MMR has a pool to choose from.
        candidate_multiplier=5,
        # Ceiling on that widened fetch, whatever max_results is asked for.
        max_candidates=100,
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
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

    # Same query without MMR, to compare against.
    plain = Knowledge(vector_db=knowledge.vector_db)
    candidates = len(await plain.asearch(query, max_results=25))

    print("\nWithout MMR")
    show(await plain.asearch(query, max_results=5), candidates)

    # Retrieves 25 candidates, selects 5 that are relevant but unlike each other.
    print("With MMR")
    show(await knowledge.asearch(query, max_results=5), candidates)

    await agent.aprint_response("What are some Thai curry dishes?", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
