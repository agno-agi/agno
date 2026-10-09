"""
Knowledge-Level Reranking
=========================
A reranker set on Knowledge runs after the vector db returns results, rather than
inside the vector db itself. Two differences follow from that:

1. It works with any vector db, so the same reranker moves between backends.
2. It widens the fetch, so the reranker chooses from a real pool rather than only
   reordering what the vector db already returned. candidate_multiplier (capped by
   max_candidates) is set on the reranker itself.

The widened fetch is what makes ordering strategies possible: a reranker can only
surface a document that was retrieved in the first place.

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
    reranker=CohereReranker(
        # Candidates fetched per requested result, so Cohere can rescue a document that
        # plain search ranked outside max_results. Costs that many times the API calls,
        # so lower it to 1 to only reorder what the vector db already returned.
        candidate_multiplier=3,
        # Ceiling on the widened fetch, once the multiplier is above 1.
        max_candidates=100,
    ),
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
