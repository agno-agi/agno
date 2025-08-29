from agno.agent import AgentKnowledge
from agno.embedder.voyageai import VoyageAIEmbedder
from agno.vectordb.pgvector import PgVector

embedder = VoyageAIEmbedder(
    id="voyage-2",
)

embeddings = embedder.get_embedding(
    "The quick brown fox jumps over the lazy dog."
)

print(f"Embeddings: {embeddings['embeddings'][:5]}")
print(f"Usage: {embeddings['usage']}")

# Contextualized embeddings
# document_chunks = [
#     ["This is the SEC filing on Leafy Inc.'s Q2 2024 performance."],
#     ["The company's revenue increased by 15% compared to the previous quarter."],
#     ["Operating expenses decreased by 3% due to cost optimization initiatives."],
#     ["The company expects continued growth in Q3 2024."]
# ]

# contextualized_result = embedder.get_contextualized_embeddings(document_chunks)
# print(f"Contextualized Embeddings count: {len(contextualized_result['embeddings'])}")
# print(f"First embedding: {contextualized_result['embeddings'][0][:5]}")
# print(f"Usage: {contextualized_result['usage']}")

# Example usage:
knowledge_base = AgentKnowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        table_name="voyageai_embeddings",
        embedder=VoyageAIEmbedder(),
    ),
    num_documents=2,
)
