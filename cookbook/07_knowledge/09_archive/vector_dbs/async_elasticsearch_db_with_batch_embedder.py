"""
Async Elasticsearch Vector Database with Batch Embedding

This example demonstrates how to use batch embedding with Elasticsearch for improved
performance when processing multiple documents.

Benefits of Batch Embedding:
- Significantly reduces API calls to embedding services
- Lower costs due to fewer API requests
- Better rate limit management
- Improved throughput for large document sets

The batch embedder processes multiple documents in a single API call, making it
ideal for scenarios with many documents to embed.

Batch embedding is used only on the async path, and only when the embedder both sets
enable_batch=True and implements async_get_embeddings_batch_and_usage. If a batch call
fails, the adapter falls back to embedding each document individually - except on a
rate limit, where falling back would issue more calls against the same limit, so the
error is raised instead.

Requirements:
- ./cookbook/scripts/run_elasticsearch.sh
- uv pip install "elasticsearch[async]"
- OPENAI_API_KEY
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.elasticsearch import Elasticsearch

# Configure Elasticsearch vector database with batch embedder
# Note: enable_batch=True enables batch embedding for async operations
vector_db = Elasticsearch(
    index_name="recipes_batch",
    # Enable batch embedding for improved performance
    embedder=OpenAIEmbedder(enable_batch=True),
)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(model=OpenAIResponses(id="gpt-5.6-luna"), knowledge=knowledge_base)


async def main():
    # Add content to the knowledge base using async operations with batch embedding
    # Comment out after first run to avoid re-indexing
    print("Adding content to knowledge base with batch embedding...")
    await knowledge_base.ainsert(url="https://docs.agno.com/agents/overview.md")
    print("Content added successfully!")

    # Query the agent
    print("\nQuerying the agent...")
    await agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)

    # The async client holds an aiohttp session that Python will not close for you:
    # skip this and the script exits with "ResourceWarning: Unclosed connector" and a
    # leaked socket. Closing also covers the sync client, which async-only use still
    # builds for the owner-mapping gate and for search.
    await vector_db.async_close()


if __name__ == "__main__":
    asyncio.run(main())
