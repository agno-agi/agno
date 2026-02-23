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
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat, OpenAIResponses

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

try:
    from agno.vectordb.lightrag import LightRag

    knowledge = Knowledge(
        vector_db=LightRag(
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            collection_name="graph_rag_demo",
            llm_model=OpenAIChat(id="gpt-4o"),
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
    )

except ImportError:
    knowledge = None
    agent = None
    print("LightRAG not installed. Run: pip install lightrag-agno")

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if knowledge and agent:
        knowledge.insert(
            url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
        )

        print("\n" + "=" * 60)
        print("Graph RAG: knowledge graph-based retrieval")
        print("=" * 60 + "\n")

        agent.print_response(
            "What ingredients are commonly shared across Thai recipes?",
            stream=True,
        )
