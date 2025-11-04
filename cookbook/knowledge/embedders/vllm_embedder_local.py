import asyncio

from agno.db.json import JsonDb
from agno.knowledge.embedder.vllm import VLLMEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector


def main():
    # Step 1: Create a local VLLMEmbedder
    embedder = VLLMEmbedder(
        id="sentence-transformers/all-MiniLM-L6-v2",
        dimensions=384,
        enforce_eager=True,
        vllm_kwargs={
            "disable_sliding_window": True,
            "max_model_len": 256,
        },
    )

    test_text = "The quick brown fox jumps over the lazy dog."
    embeddings = embedder.get_embedding(test_text)
    print(f"   Text: {test_text}")
    print(f"   Embedding dimensions: {len(embeddings)}")
    print(f"   First 5 values: {embeddings[:5]}")

    # Step 3: Create Knowledge base with local embedder
    knowledge = Knowledge(
        vector_db=PgVector(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            table_name="vllm_embeddings_minilm_local",
            embedder=VLLMEmbedder(
                id="sentence-transformers/all-MiniLM-L6-v2",
                dimensions=384,
                enforce_eager=True,
                vllm_kwargs={
                    "disable_sliding_window": True,
                    "max_model_len": 256,
                },
            ),
        ),
        contents_db=JsonDb(
            db_path="./knowledge_contents",
            knowledge_table="vllm_local_knowledge",
        ),
        max_results=2,
    )

    # Step 4: Load documents
    asyncio.run(
        knowledge.add_content_async(
            path="cookbook/knowledge/testing_resources/cv_1.pdf",
        )
    )
    query = "What are the candidate's skills?"
    results = knowledge.search(query=query)
    print(f"   Query: {query}")
    print(f"   Results found: {len(results)}")
    for i, result in enumerate(results, 1):
        print(f"   Result {i}: {result.content[:100]}...")


if __name__ == "__main__":
    main()
