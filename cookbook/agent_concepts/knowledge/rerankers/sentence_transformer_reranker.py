from agno.agent import AgentKnowledge
from agno.document import Document
from agno.embedder.sentence_transformer import SentenceTransformerEmbedder
from agno.reranker.sentence_transformer import SentenceTransformerReranker
from agno.vectordb.pgvector import PgVector

reranker = SentenceTransformerReranker(model="BAAI/bge-reranker-v2-m3")

query = "Organic skincare products for sensitive skin"
search_results = [
    "Organic skincare for sensitive skin with aloe vera and chamomile.",
    "New makeup trends focus on bold colors and innovative techniques",
    "Bio-Hautpflege für empfindliche Haut mit Aloe Vera und Kamille",
    "Neue Make-up-Trends setzen auf kräftige Farben und innovative Techniken",
    "Cuidado de la piel orgánico para piel sensible con aloe vera y manzanilla",
    "Las nuevas tendencias de maquillaje se centran en colores vivos y técnicas innovadoras",
    "针对敏感肌专门设计的天然有机护肤产品",
    "新的化妆趋势注重鲜艳的颜色和创新的技巧",
    "敏感肌のために特別に設計された天然有機スキンケア製品",
    "新しいメイクのトレンドは鮮やかな色と革新的な技術に焦点を当てています",
]

documents = [Document(content=result) for result in search_results]

reranked_documents = reranker.rerank(query, documents)

for doc in reranked_documents:
    print(f"Reranked Document: {doc.content}")
    print(f"Reranking Score: {doc.reranking_score}")
    print("-" * 100)

# Example usage:
knowledge_base = AgentKnowledge(
    vector_db=PgVector(
        db_url="postgresql+psycopg://ai:ai@localhost:5432/ai",
        table_name="sentence_transformer_embeddings",
        embedder=SentenceTransformerEmbedder(),
        reranker=SentenceTransformerReranker(model="BAAI/bge-reranker-v2-m3"),
    ),
    num_documents=2,
)
