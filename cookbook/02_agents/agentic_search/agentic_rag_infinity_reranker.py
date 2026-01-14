"""This cookbook shows how to implement Agentic RAG using Infinity Reranker.

Infinity is a high-performance inference server for text-embeddings, reranking, and classification models.
It provides fast and efficient reranking capabilities for RAG applications.

## Setup Instructions:

### 1. Install Dependencies
Run: `pip install agno anthropic infinity-client lancedb`

### 2. Set up Infinity Server
You have several options to deploy Infinity:

#### Local Installation
```bash
# Install infinity
pip install "infinity-emb[all]"

# Run infinity server with reranking model
infinity_emb v2 --model-id BAAI/bge-reranker-base --port 7997
```
Wait for the engine to start.

# For better performance, you can use larger models:
# BAAI/bge-reranker-large
# BAAI/bge-reranker-v2-m3
# ms-marco-MiniLM-L-12-v2


### 3. Export API Keys
```bash
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

### 4. Run the Example
```bash
python cookbook/agent_concepts/agentic_search/agentic_rag_infinity_reranker.py
```

## About Infinity Reranker:
- Provides fast, local reranking without external API calls
- Supports multiple state-of-the-art reranking models
- Can be deployed on GPU for better performance
- Offers both sync and async reranking capabilities
- More deployment options: https://michaelfeil.eu/infinity/0.0.76/deploy/
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.infinity import InfinityReranker
from agno.models.anthropic import Claude
from agno.vectordb.lancedb import LanceDb, SearchType

knowledge = Knowledge(
    # Use LanceDB as the vector database, store embeddings in the `agno_docs_infinity` table
    vector_db=LanceDb(
        uri="tmp/lancedb",
        table_name="agno_docs_infinity",
        search_type=SearchType.hybrid,
        embedder=CohereEmbedder(id="embed-v4.0"),
        # Use Infinity reranker for local, fast reranking
        reranker=InfinityReranker(
            model="BAAI/bge-reranker-base",  # You can change this to other models
            host="localhost",
            port=7997,
            top_n=5,  # Return top 5 reranked documents
        ),
    ),
)
asyncio.run(
    knowledge.add_contents_async(
        urls=[
            "https://docs.agno.com/basics/agents/overview.md",
            "https://docs.agno.com/basics/tools/overview.md",
            "https://docs.agno.com/basics/knowledge/overview.md",
        ]
    )
)

agent = Agent(
    model=Claude(id="claude-3-7-sonnet-latest"),
    # Agentic RAG is enabled by default when `knowledge` is provided to the Agent.
    knowledge=knowledge,
    # search_knowledge=True gives the Agent the ability to search on demand
    # search_knowledge is True by default
    search_knowledge=True,
    instructions=[
        "Include sources in your response.",
        "Always search your knowledge before answering the question.",
        "Provide detailed and accurate information based on the retrieved documents.",
    ],
    markdown=True,
)


def test_infinity_connection():
    """Test if Infinity server is running and accessible"""
    try:
        from infinity_client import Client

        _ = Client(base_url="http://localhost:7997")
        print("✅ Successfully connected to Infinity server at localhost:7997")
        return True
    except Exception as e:
        print(f"❌ Failed to connect to Infinity server: {e}")
        print(
            "\nPlease make sure Infinity server is running. See setup instructions above."
        )
        return False


if __name__ == "__main__":
    print("🚀 Agentic RAG with Infinity Reranker Example")
    print("=" * 50)

    # Test Infinity connection first
    if not test_infinity_connection():
        exit(1)

    print("\n🤖 Starting agent interaction...")
    print("=" * 50)

    # Example questions to test the reranking capabilities
    questions = [
        "What are Agents and how do they work?",
        "How do I use tools with agents?",
        "What is the difference between knowledge and tools?",
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n🔍 Question {i}: {question}")
        print("-" * 40)
        agent.print_response(question, stream=True)
        print("\n" + "=" * 50)

    print("\n🎉 Example completed!")
    print("\nThe Infinity reranker helped improve the relevance of retrieved documents")
    print("by reranking them based on semantic similarity to your queries.")
