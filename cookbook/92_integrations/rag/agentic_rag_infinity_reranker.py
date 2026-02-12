"""
Agentic Rag Infinity Reranker
=============================

Demonstrates agentic RAG with an Infinity reranker backend (relocated integration example).
"""

import asyncio
import importlib

from agno.agent import Agent
from agno.knowledge.embedder.cohere import CohereEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.infinity import InfinityReranker
from agno.models.anthropic import Claude
from agno.vectordb.lancedb import LanceDb, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
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
        infinity_client = importlib.import_module("infinity_client")
        _ = infinity_client.Client(base_url="http://localhost:7997")
        print("[OK] Successfully connected to Infinity server at localhost:7997")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to connect to Infinity server: {e}")
        print(
            "\nPlease make sure Infinity server is running. See setup instructions above."
        )
        return False


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Agentic RAG with Infinity Reranker Example")
    print("=" * 50)

    # Load knowledge base
    print("\nLoading knowledge base...")
    asyncio.run(
        knowledge.ainsert_many(
            urls=[
                "https://docs.agno.com/basics/agents/overview.md",
                "https://docs.agno.com/basics/tools/overview.md",
                "https://docs.agno.com/basics/knowledge/overview.md",
            ]
        )
    )

    # Test Infinity connection first
    if not test_infinity_connection():
        exit(1)

    print("\nStarting agent interaction...")
    print("=" * 50)

    # Example questions to test the reranking capabilities
    questions = [
        "What are Agents and how do they work?",
        "How do I use tools with agents?",
        "What is the difference between knowledge and tools?",
    ]

    for i, question in enumerate(questions, 1):
        print(f"\n[Question {i}] {question}")
        print("-" * 40)
        agent.print_response(question, stream=True)
        print("\n" + "=" * 50)

    print("\nExample completed!")
    print("\nThe Infinity reranker helped improve the relevance of retrieved documents")
    print("by reranking them based on semantic similarity to your queries.")
