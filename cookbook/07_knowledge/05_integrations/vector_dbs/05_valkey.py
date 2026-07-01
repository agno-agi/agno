"""
Valkey: High-Performance Vector Search
========================================
Valkey is an open-source, high-performance key-value store with
native vector search via ValkeySearch. This integration uses the
valkey-glide-sync client for direct ValkeySearch support.

Features:
- Vector similarity search (KNN / ANN)
- HNSW and FLAT indexing algorithms
- Cosine, L2, and inner-product distance metrics
- Reranking support
- Async and sync operation modes

Setup:
  docker run --name my-valkey -p 6379:6379 -d valkey/valkey-bundle

Requires: pip install valkey-glide-sync pypdf
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.valkey import ValkeyVectorDb

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

knowledge = Knowledge(
    vector_db=ValkeyVectorDb(
        index_name="valkey_cookbook",
        host="localhost",
        port=6379,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    print("\n" + "=" * 60)
    print("Valkey: Vector similarity search")
    print("=" * 60 + "\n")

    knowledge.insert(url=pdf_url)
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
    )
    agent.print_response("What Thai recipes do you know?", stream=True)
