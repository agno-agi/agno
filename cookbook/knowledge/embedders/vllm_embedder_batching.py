import asyncio

from agno.knowledge.embedder.vllm import VLLMEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector


def main():
    # Basic usage - local mode
    embeddings = VLLMEmbedder(
        id="intfloat/e5-mistral-7b-instruct",
        dimensions=4096,
        enforce_eager=True,
        vllm_kwargs={
            "disable_sliding_window": True,
            "max_model_len": 4096,
        },
    ).get_embedding("The quick brown fox jumps over the lazy dog.")

    # Print the embeddings and their dimensions
    print(f"Embeddings: {embeddings[:5]}")
    print(f"Dimensions: {len(embeddings)}")

    # Example usage with Local Knowledge - Local mode with batching
    knowledge = Knowledge(
        vector_db=PgVector(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            table_name="vllm_embeddings_batch",
            embedder=VLLMEmbedder(
                id="intfloat/e5-mistral-7b-instruct",
                dimensions=4096,
                enforce_eager=True,
                enable_batch=True,
                batch_size=10,
                vllm_kwargs={
                    "disable_sliding_window": True,
                    "max_model_len": 4096,
                },
            ),
        ),
        max_results=2,
    )

    # Example usage with Knowledge - Remote mode with batching
    knowledge_remote = Knowledge(
        vector_db=PgVector(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            table_name="vllm_embeddings_remote_batch",
            embedder=VLLMEmbedder(
                id="intfloat/e5-mistral-7b-instruct",
                dimensions=4096,
                base_url="http://localhost:8000/v1",  # Your VLLM server URL
                api_key="your-api-key",  # Optional
                enable_batch=True,
                batch_size=100,  # Higher batch size for remote API
            ),
        ),
        max_results=2,
    )

    asyncio.run(
        knowledge.add_content_async(
            path="cookbook/knowledge/testing_resources/cv_1.pdf",
        )
    )


if __name__ == "__main__":
    main()
