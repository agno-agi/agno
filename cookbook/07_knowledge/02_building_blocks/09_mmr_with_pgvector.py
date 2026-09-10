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

if __name__ == "__main__":

    async def main():
        await knowledge.ainsert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        print("\n" + "=" * 60)
        print("PgVector hybrid search + MMR")
        print("=" * 60 + "\n")

        # Retrieves 25 candidates, selects 5 that are relevant but unlike each other.
        results = await knowledge.asearch(
            "What are some Thai curry dishes?", max_results=5
        )
        for document in results:
            print(f"  {document.name}")

        await agent.aprint_response("What are some Thai curry dishes?", stream=True)

    asyncio.run(main())
