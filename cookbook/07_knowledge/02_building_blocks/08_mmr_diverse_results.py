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
knowledge-level reranker provides: rerank_multiplier widens the fetch, MMR selects
from it, and max_results are returned.

MMR reads the embedding on each search result. Not every vector db returns one:
Milvus, MongoDB, Redis, Valkey and Elasticsearch do not, so MMR raises there rather
than silently returning unreranked results.

Take the returned order as the result: reranking_score holds the MMR score at the
moment each document was picked, which is not descending, so re-sorting by it discards
the diversity ordering.

A reranker set on the vector db still runs first, on the widened pool, and MMR then
reorders its output. Scoring by relevance and then by embedding similarity rarely
composes usefully, so prefer setting one or the other.

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
    reranker=MMRReranker(lambda_mult=0.5),
    # Retrieve 5x the requested results so MMR has candidates to choose between.
    rerank_multiplier=5,
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

    # Retrieves 25 candidates, selects 5 that are relevant but unlike each other.
    results = await knowledge.asearch("What are some Thai curry dishes?", max_results=5)
    print("Diverse results:")
    for document in results:
        print(f"  {document.name}")

    await agent.aprint_response("What are some Thai curry dishes?", stream=True)


if __name__ == "__main__":
    asyncio.run(main())
