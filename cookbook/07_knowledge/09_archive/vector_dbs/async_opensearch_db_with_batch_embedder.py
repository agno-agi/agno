"""
Async OpenSearch Vector Database with Batch Embedding

This example demonstrates how to use batch embedding with OpenSearch for improved
performance when processing multiple documents.

Benefits of Batch Embedding:
- Significantly reduces API calls to embedding services
- Lower costs due to fewer API requests
- Better rate limit management
- Improved throughput for large document sets

The batch embedder processes multiple documents in a single API call, making it
ideal for scenarios with many documents to embed.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.opensearch import OpenSearch

# Configure OpenSearch vector database with batch embedder
# Note: enable_batch=True enables batch embedding for async operations
vector_db = OpenSearch(
    index_name="recipes_batch",
    # Enable batch embedding for improved performance
    embedder=OpenAIEmbedder(enable_batch=True),
)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(model=OpenAIResponses(id="gpt-5.5"), knowledge=knowledge_base)


async def main():
    # Add content to the knowledge base using async operations with batch embedding
    # Comment out after first run to avoid re-indexing
    print("Adding content to knowledge base with batch embedding...")
    await knowledge_base.add_content_async(
        url="https://docs.agno.com/agents/overview.md"
    )
    print("Content added successfully!")

    # Query the agent
    print("\nQuerying the agent...")
    await agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)

    # Release the underlying aiohttp session
    await vector_db.async_close()


if __name__ == "__main__":
    asyncio.run(main())
