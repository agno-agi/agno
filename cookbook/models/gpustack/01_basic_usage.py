"""
Basic usage examples for GPUStack with Agno.

This example demonstrates how to use GPUStack's native API implementation
with Agno for various AI tasks.

Prerequisites:
1. Install and run GPUStack: https://docs.gpustack.ai/latest/installation/
2. Deploy models on GPUStack for each task you want to run
3. Set environment variables:
   - GPUSTACK_SERVER_URL: Your GPUStack server URL
   - GPUSTACK_API_KEY: Your GPUStack API key

Run:
    python cookbook/models/gpustack/01_basic_usage.py
"""

import os

from agno.agent import Agent
from agno.models.gpustack import (
    GPUStack,
    GPUStackChat,
    GPUStackEmbeddings,
    GPUStackRerank,
)


def chat_example():
    """Example of using GPUStack for chat completions."""
    print("=== Chat Completions Example ===\n")

    # Create a chat model
    model = GPUStackChat(
        id="llama3",  # Replace with your deployed model
        temperature=0.7,
        max_tokens=500,
    )

    # Create an agent
    agent = Agent(
        model=model,
        description="A helpful AI assistant powered by GPUStack",
        instructions=["Be informative and concise"],
    )

    # Get a response
    response = agent.run("What are the benefits of using GPUStack for AI deployments?")
    print(f"Assistant: {response.content}\n")


def embeddings_example():
    """Example of generating text embeddings."""
    print("=== Embeddings Example ===\n")

    # Create embeddings model
    embeddings = GPUStackEmbeddings(id="bge-m3")

    # Generate embeddings for multiple texts
    texts = [
        "GPUStack is a GPU cluster management platform",
        "Machine learning models require computational resources",
        "Python is a popular programming language",
    ]

    print(f"Generating embeddings for {len(texts)} texts...")
    result = embeddings.embed(texts)

    # Parse embeddings
    vectors = embeddings.parse_embeddings_response(result)
    print(f"Generated {len(vectors)} embeddings")
    print(f"Embedding dimension: {len(vectors[0]) if vectors else 0}\n")


def rerank_example():
    """Example of document reranking."""
    print("=== Document Reranking Example ===\n")

    # Create reranker
    reranker = GPUStackRerank(
        id="bge-reranker-v2-m3",
        top_n=3,
    )

    # Documents to rerank
    documents = [
        "GPUStack simplifies GPU cluster management for AI workloads",
        "The weather today is sunny and warm",
        "GPU acceleration is essential for modern AI models",
        "Coffee is a popular morning beverage",
        "Distributed computing enables scaling of AI applications",
    ]

    query = "GPU computing for artificial intelligence"

    print(f"Query: {query}")
    print(f"Reranking {len(documents)} documents...\n")

    result = reranker.rerank(query=query, documents=documents)

    # Display reranked results
    for item in reranker.parse_rerank_response(result):
        print(f"Rank {item['index'] + 1}: Score {item['relevance_score']:.4f}")
        if "document" in item:
            print(f"  Document: {item['document'][:100]}...")
        print()


def unified_interface_example():
    """Example using the unified GPUStack interface."""
    print("=== Unified Interface Example ===\n")

    # Create different models using unified interface
    models = {
        "chat": GPUStack(model_type="chat", id="llama3"),
        "embeddings": GPUStack(model_type="embeddings", id="bge-m3"),
        "rerank": GPUStack(model_type="rerank", id="bge-reranker-v2-m3"),
    }

    for model_type, model in models.items():
        print(f"Created {model_type} model: {model.__class__.__name__}")
        print(f"  Model ID: {model.id}")
        print(f"  Base URL: {model.base_url}")
        print()


def streaming_example():
    """Example of streaming chat responses."""
    print("=== Streaming Chat Example ===\n")

    model = GPUStackChat(id="llama3")

    # Create agent for streaming
    agent = Agent(
        model=model,
        description="A streaming assistant",
    )

    print("Assistant: ", end="", flush=True)

    try:
        # Stream the response
        messages = [{"role": "user", "content": "Tell me a very short story about AI."}]

        for chunk in model.invoke_stream(messages):
            response = model.parse_provider_response_delta(chunk)
            if response.content:
                print(response.content, end="", flush=True)

        print("\n")
    except Exception as e:
        print(f"\nStreaming failed: {e}\n")


def async_example():
    """Example of async operations."""
    print("=== Async Operations Example ===\n")

    import asyncio

    async def run_async():
        # Create models
        chat = GPUStackChat(id="llama3")
        embeddings = GPUStackEmbeddings(id="bge-m3")

        # Async chat
        messages = [{"role": "user", "content": "What is async programming?"}]
        chat_result = await chat.ainvoke(messages)
        parsed_chat = chat.parse_provider_response(chat_result)
        print(f"Chat response: {parsed_chat.content[:100]}...\n")

        # Async embeddings
        embed_result = await embeddings.aembed("Async programming in Python")
        vectors = embeddings.parse_embeddings_response(embed_result)
        print(f"Embedding dimension: {len(vectors[0]) if vectors else 0}\n")

    # Run async example
    try:
        asyncio.run(run_async())
    except Exception as e:
        print(f"Async example failed: {e}\n")


if __name__ == "__main__":
    print("GPUStack Native API Examples with Agno\n")
    print("=" * 50)
    print()

    # Check environment
    if not os.getenv("GPUSTACK_SERVER_URL"):
        print("Warning: GPUSTACK_SERVER_URL not set")
    if not os.getenv("GPUSTACK_API_KEY"):
        print("Warning: GPUSTACK_API_KEY not set")
    print()

    # Run examples
    try:
        # Basic examples
        chat_example()
        embeddings_example()
        rerank_example()

        # Other examples
        unified_interface_example()
        # streaming_example()
        # async_example()

    except Exception as e:
        print(f"\nError running examples: {e}")
        print("\nTroubleshooting:")
        print("1. Ensure GPUStack is running and accessible")
        print("2. Check that required models are deployed")
        print("3. Verify environment variables are set correctly")
