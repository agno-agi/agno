from phi.agent import AgentKnowledge
from phi.vectordb.pgvector import PgVector
from phi.embedder.langdb import LangDBEmbedder

embeddings = LangDBEmbedder().get_embedding("Embed me")

# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage:
knowledge_base = AgentKnowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="openai_embeddings",
        embedder=LangDBEmbedder(),
    ),
    num_documents=2,
)
