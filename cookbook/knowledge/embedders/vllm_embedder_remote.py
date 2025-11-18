import asyncio

from agno.db.json import JsonDb
from agno.knowledge.embedder.vllm import VLLMEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector


def main():
    # Step 1: Create a remote VLLMEmbedder
    embedder = VLLMEmbedder(
        id="sentence-transformers/all-MiniLM-L6-v2",
        dimensions=384,
        base_url="http://localhost:8000/v1",
        api_key="your-api-key",  # Optional - depends on server configuration
    )

    # Step 2: Generate a test embedding
    test_text = "The quick brown fox jumps over the lazy dog."
    try:
        embeddings = embedder.get_embedding(test_text)
        print(f"Text: {test_text}")
        print(f"Embedding dimensions: {len(embeddings)}")
        print(f"First 5 values: {embeddings[:5]}")
    except Exception as e:
        print(f"Error connecting to remote server: {e}")
        return

    # Step 3: Create Knowledge base with remote embedder
    knowledge = Knowledge(
        vector_db=PgVector(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            table_name="vllm_embeddings_minilm_remote",
            embedder=VLLMEmbedder(
                id="sentence-transformers/all-MiniLM-L6-v2",
                dimensions=384,
                base_url="http://localhost:8000/v1",
                api_key="your-api-key",  # Optional
            ),
        ),
        contents_db=JsonDb(
            db_path="./knowledge_contents",
            knowledge_table="vllm_remote_knowledge",
        ),
        max_results=2,
    )

    # Step 4: Load documents
    try:
        asyncio.run(
            knowledge.add_content_async(
                path="cookbook/knowledge/testing_resources/cv_1.pdf",
            )
        )
        print("   ✓ Documents loaded")
    except Exception as e:
        print(f"   ✗ Error loading documents: {e}")
        return

    # Step 5: Search the knowledge base
    query = "What are the candidate's skills?"
    try:
        results = knowledge.search(query=query)
        print(f"   Query: {query}")
        print(f"   Results found: {len(results)}")
        for i, result in enumerate(results, 1):
            print(f"   Result {i}: {result.content[:100]}...")
    except Exception as e:
        print(f"   ✗ Error searching: {e}")
        return


if __name__ == "__main__":
    main()
