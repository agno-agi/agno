import asyncio

from agno.knowledge.embedder.jina import JinaEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Basic usage - automatically loads from JINA_API_KEY environment variable
embeddings = JinaEmbedder().get_embedding(
    "The quick brown fox jumps over the lazy dog."
)

# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

custom_embedder = JinaEmbedder(
    dimensions=1024,
    late_chunking=True,  # Improved processing for long documents
    timeout=30.0,  # Request timeout in seconds
)

# Get embedding with usage information
embedding, usage = custom_embedder.get_embedding_and_usage(
    "Advanced text processing with Jina embeddings and late chunking."
)
print(f"Embedding dimensions: {len(embedding)}")
if usage:
    print(f"Usage info: {usage}")

# Example usage with Knowledge
knowledge = Knowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="jina_embeddings",
        embedder=JinaEmbedder(
            late_chunking=True,  # Better handling of long documents
            timeout=30.0,  # Configure request timeout
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
