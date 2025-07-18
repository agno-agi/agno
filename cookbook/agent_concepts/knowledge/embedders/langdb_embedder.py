from agno.agent import AgentKnowledge
from agno.embedder.langdb import LangDBEmbedder
from agno.vectordb.pgvector import PgVector

embeddings = LangDBEmbedder().get_embedding("Embed me")

# Print the embeddings and their dimensions
print(f"Embeddings: {embeddings[:5]}")
print(f"Dimensions: {len(embeddings)}")

# Example usage:
knowledge_base = AgentKnowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="langdb_embeddings",
        embedder=LangDBEmbedder(),
    ),
    num_documents=2,
)
