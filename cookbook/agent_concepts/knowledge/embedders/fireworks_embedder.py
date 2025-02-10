from agno.agent import AgentKnowledge
from agno.embedder.fireworks import FireworksEmbedder
from agno.vectordb.pgvector import PgVector

embeddings = FireworksEmbedder().get_embedding(
    "The quick brown fox jumps over the lazy dog."
)

# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage:
knowledge_base = AgentKnowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="fireworks_embeddings",
        embedder=FireworksEmbedder(),
    ),
    num_documents=2,
)
