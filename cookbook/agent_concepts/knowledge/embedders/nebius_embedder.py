from agno.agent import AgentKnowledge
from agno.embedder.nebius import NebiusEmbedder
from agno.vectordb.pgvector import PgVector

embeddings = NebiusEmbedder().get_embedding(
    "The quick brown fox jumps over the lazy dog."
)

# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage:
knowledge_base = AgentKnowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="nebius_embeddings",
        embedder=NebiusEmbedder(),
    ),
    num_documents=2,
)
