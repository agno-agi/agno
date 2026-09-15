"""
MMR with PgVector
=================
The same diversity selection as 08_mmr_diverse_results.py, against PgVector.

MMR compares candidates to each other, so it needs the embedding of every search
result. PgVector returns embeddings on search, so MMR works against it directly.

Setup:
    ./cookbook/scripts/run_pgvector.sh

See also: 08_mmr_diverse_results.py for what lambda_mult controls.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.mmr import MMRReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="mmr_demo",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    # Runs after PgVector returns candidates.
    reranker=MMRReranker(lambda_mult=0.5),
    # Retrieve 5x the requested results so MMR has candidates to choose between.
    rerank_multiplier=5,
)

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    knowledge=knowledge,
    search_knowledge=True,
    instructions=[
        "Always search your knowledge base before answering.",
        "Include sources in your response.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------


def show(results, candidates: int) -> None:
    """Print a snippet per result: every chunk shares the source file name."""
    print(f"Selected {len(results)} of {candidates} candidates:\n")
    for document in results:
        snippet = " ".join(document.content.split())[:100]
        print(f"  - {snippet}...")
    print()


if __name__ == "__main__":

    async def main():
        await knowledge.ainsert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        print("\n" + "=" * 60)
        print("PgVector hybrid search + MMR")
        print("=" * 60 + "\n")

        query = "What are some Thai curry dishes?"

        # Same query without MMR, to compare against.
        plain = Knowledge(vector_db=knowledge.vector_db)
        candidates = len(await plain.asearch(query, max_results=25))

        print("Without MMR")
        show(await plain.asearch(query, max_results=5), candidates)

        # Retrieves 25 candidates, selects 5 that are relevant but unlike each other.
        print("With MMR")
        show(await knowledge.asearch(query, max_results=5), candidates)

        await agent.aprint_response("What are some Thai curry dishes?", stream=True)

    asyncio.run(main())
