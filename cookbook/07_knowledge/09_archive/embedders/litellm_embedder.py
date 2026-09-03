"""
LiteLLM Embedder
================

Demonstrates LiteLLM embeddings and knowledge insertion, including a batching variant.

LiteLLM is a client-side routing library: it translates one call signature into
whichever provider the model string names, then calls that provider's API
directly. There is no LiteLLM account or LiteLLM API key. You supply the
provider's own key, for example OPENAI_API_KEY for an "openai/..." model.

Requirements:
- pip install litellm
- A provider key for the model you choose, e.g. export OPENAI_API_KEY=...
- PostgreSQL with pgvector running

Model strings follow "<provider>/<model>", for example:
- openai/text-embedding-3-small
- openai/text-embedding-3-large
- cohere/embed-english-v3.0
"""

import asyncio

from agno.knowledge.embedder.litellm import LiteLLMEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
def create_knowledge() -> Knowledge:
    # dimensions must match the model: LiteLLMEmbedder does not derive it from
    # the model string, so the base default of 1536 is used unless set here.
    # Standard mode
    embedder = LiteLLMEmbedder(id="openai/text-embedding-3-small", dimensions=1536)

    # Batching mode (uncomment to use)
    # embedder = LiteLLMEmbedder(
    #     id="openai/text-embedding-3-small",
    #     dimensions=1536,
    #     enable_batch=True,
    #     batch_size=100,
    # )

    return Knowledge(
        vector_db=PgVector(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            table_name="litellm_embeddings",
            embedder=embedder,
        ),
        max_results=2,
    )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    embeddings = LiteLLMEmbedder(id="openai/text-embedding-3-small").get_embedding(
        "The quick brown fox jumps over the lazy dog."
    )
    print(f"Embeddings: {embeddings[:5]}")
    print(f"Dimensions: {len(embeddings)}")

    knowledge = create_knowledge()
    await knowledge.ainsert(path="cookbook/07_knowledge/testing_resources/cv_1.pdf")


if __name__ == "__main__":
    asyncio.run(main())
