"""
Graph RAG: LightRAG Integration
=================================
LightRAG is a managed knowledge backend that builds a knowledge graph
from your documents. It handles its own ingestion and retrieval,
providing graph-based RAG capabilities.

Unlike standard vector-based RAG, LightRAG:
- Extracts entities and relationships from documents
- Builds a knowledge graph for multi-hop reasoning
- Supports graph-traversal queries

Requirements: pip install lightrag-agno
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

try:
    from agno.vectordb.lightrag import LightRag

    # LightRag connects to a running LightRAG server.
    # Start one with: lightrag-server --host 0.0.0.0 --port 9621
    lightrag = LightRag(server_url="http://localhost:9621")

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge_retriever=lightrag.lightrag_knowledge_retriever,
        search_knowledge=True,
        markdown=True,
    )

except ImportError:
    lightrag = None
    agent = None
    print("LightRAG not installed. Run: pip install lightrag-agno")

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if lightrag and agent:
        # Note: Documents must be ingested into LightRAG via its own API
        # (e.g. lightrag.insert_file_bytes or lightrag.insert_text).
        # The server handles chunking, entity extraction, and graph building.

        print("\n" + "=" * 60)
        print("Graph RAG: knowledge graph-based retrieval")
        print("=" * 60 + "\n")

        agent.print_response(
            "What ingredients are commonly shared across Thai recipes?",
            stream=True,
        )
