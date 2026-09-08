"""
Siliconflow Embedding and Reranking
===================================

Demonstrates Siliconflow text embeddings and reranking without a vector database.

Set SILICONFLOW_API_KEY before running this example.
"""

from agno.knowledge.document import Document
from agno.knowledge.embedder.siliconflow import SiliconflowEmbedder
from agno.knowledge.reranker.siliconflow import SiliconflowReranker

# ---------------------------------------------------------------------------
# Create Siliconflow Clients
# ---------------------------------------------------------------------------
embedder = SiliconflowEmbedder()
reranker = SiliconflowReranker(top_n=2, raise_on_error=True)

query = "Where is the Eiffel Tower?"
documents = [
    Document(content="The Eiffel Tower is in Paris."),
    Document(content="Python is a programming language."),
    Document(content="Paris is the capital of France."),
]


# ---------------------------------------------------------------------------
# Run Embedding and Reranking
# ---------------------------------------------------------------------------
def main() -> None:
    texts = [query, *[document.content for document in documents]]
    embeddings, usages = embedder.get_embeddings_batch_and_usage(texts)

    query_embedding = embeddings[0]
    for document, embedding in zip(documents, embeddings[1:]):
        document.embedding = embedding

    print(f"Query embedding dimensions: {len(query_embedding)}")
    if usages[0] is not None:
        print("Usage is reported for the entire embedding batch.")

    reranked_documents = reranker.rerank(query, documents)
    print("Reranked documents:")
    for document in reranked_documents:
        print(f"- {document.reranking_score:.4f}: {document.content}")


if __name__ == "__main__":
    main()
