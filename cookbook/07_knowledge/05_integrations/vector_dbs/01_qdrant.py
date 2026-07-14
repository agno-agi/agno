"""
Qdrant: Recommended Vector Database
=====================================
Qdrant is the recommended vector database for production use.
It provides fast, scalable vector search with rich filtering
capabilities, hybrid search, and reranking support.

Features:
- Vector, keyword, and hybrid search
- Reranking support
- Rich metadata filtering
- Cloud or self-hosted deployment options

Setup: ./cookbook/scripts/run_qdrant.sh

See also: 02_local.py for local dev, 03_managed.py for Pinecone, 04_pgvector.py for PostgreSQL.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.qdrant import Qdrant, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# --- Basic Qdrant setup ---
knowledge_basic = Knowledge(
    vector_db=Qdrant(
        collection="qdrant_basic",
        url="http://localhost:6333",
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# --- Hybrid search with reranking ---
knowledge_advanced = Knowledge(
    vector_db=Qdrant(
        collection="qdrant_advanced",
        url="http://localhost:6333",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        reranker=CohereReranker(model="rerank-multilingual-v3.0"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Basic vector search ---
    print("\n" + "=" * 60)
    print("Qdrant: Basic vector search")
    print("=" * 60 + "\n")

    knowledge_basic.insert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge_basic,
        search_knowledge=True,
        markdown=True,
    )
    agent.print_response("What Thai recipes do you know?", stream=True)

    # --- Hybrid search with reranking ---
    print("\n" + "=" * 60)
    print("Qdrant: Hybrid search + Cohere reranking")
    print("=" * 60 + "\n")

    knowledge_advanced.insert(
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"
    )
    agent_advanced = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge_advanced,
        search_knowledge=True,
        markdown=True,
    )
    agent_advanced.print_response("What Thai desserts are available?", stream=True)
