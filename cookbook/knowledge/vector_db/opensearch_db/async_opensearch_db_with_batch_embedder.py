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
from agno.models.openai import OpenAIChat
from agno.vectordb.opensearch import OpensearchDb

# Configure OpenSearch vector database with batch embedder
# Note: enable_batch=True enables batch embedding for async operations
vector_db = OpensearchDb(
    index_name="recipes_batch",
    dimension=1536,
    hosts=[
        {
            "host": "localhost",
            "port": 9200,
        }
    ],
    # Uncomment the following line to use basic authentication
    # http_auth=("username", "password"),
    # Enable batch embedding for improved performance
    embedder=OpenAIEmbedder(enable_batch=True),
)

knowledge_base = Knowledge(
    vector_db=vector_db,
)

agent = Agent(model=OpenAIChat(id="gpt-4o-mini"), knowledge=knowledge_base)

if __name__ == "__main__":
    # Add content to the knowledge base using async operations with batch embedding
    # Comment out after first run to avoid re-indexing
    print("Adding content to knowledge base with batch embedding...")
    asyncio.run(
        knowledge_base.add_content_async(
            url="https://docs.agno.com/concepts/agents/introduction.md"
        )
    )
    print("Content added successfully!")

    # Query the agent
    print("\nQuerying the agent...")
    asyncio.run(
        agent.aprint_response("What is the purpose of an Agno Agent?", markdown=True)
    )
