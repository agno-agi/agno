import asyncio

from agno.knowledge.embedder.google import GeminiEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

embeddings = GeminiEmbedder().get_embedding(
    "The quick brown fox jumps over the lazy dog."
)

# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage:
knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="gemini_embeddings",
        embedder=GeminiEmbedder(
            enable_batch=True,
        ),
    ),
    max_results=2,
)

asyncio.run(
    knowledge.add_content_async(
        path="cookbook/knowledge/testing_resources/cv_1.pdf",
    )
)
