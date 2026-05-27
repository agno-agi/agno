"""
Azure OpenAI Embedder
=====================

Demonstrates Azure OpenAI embeddings and knowledge insertion, including a batching variant.
"""

import asyncio

from agno.knowledge.embedder.azure_openai import AzureOpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
def create_knowledge() -> Knowledge:
    # Standard mode
    embedder = AzureOpenAIEmbedder()

    # Batching mode (uncomment to use)
    # embedder = AzureOpenAIEmbedder(enable_batch=True)

    return Knowledge(
        vector_db=PgVector(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            table_name="azure_openai_embeddings",
            embedder=embedder,
        ),
        max_results=2,
    )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
async def main() -> None:
    embeddings = AzureOpenAIEmbedder(id="text-embedding-3-small").get_embedding(
        "The quick brown fox jumps over the lazy dog."
    )
    print(f"Embeddings: {embeddings[:5]}")
    print(f"Dimensions: {len(embeddings)}")

    knowledge = create_knowledge()
    await knowledge.ainsert(path="cookbook/07_knowledge/testing_resources/cv_1.pdf")


if __name__ == "__main__":
    asyncio.run(main())
