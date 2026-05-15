"""
TopK: Vector Database Integration
===================================
TopK Database powers scalable vector, keyword (BM25), and hybrid search.

Features:
- Vector search with configurable distance metrics (cosine, euclidean, dot product)
- Keyword search (BM25)
- Hybrid search (vector distance with keyword boosting)
- Async support

Setup:
    pip install topk_sdk
    export TOPK_API_KEY=your_api_key
    export TOPK_REGION=your_region

Get your API: https://console.topk.io
See available regions: https://docs.topk.io/regions
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.search import SearchType
from agno.vectordb.topk import TopK

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

embedder = OpenAIEmbedder(id="text-embedding-3-small")

# --- Basic vector search ---
knowledge_vector = Knowledge(
    vector_db=TopK(
        collection="topk_vector",
        embedder=embedder,
        search_type=SearchType.vector,
    ),
)

# --- Keyword (BM25) search ---
knowledge_keyword = Knowledge(
    vector_db=TopK(
        collection="topk_keyword",
        embedder=embedder,
        search_type=SearchType.keyword,
    ),
)

# --- Hybrid search (vector + keyword boost) ---
knowledge_hybrid = Knowledge(
    vector_db=TopK(
        collection="topk_hybrid",
        embedder=embedder,
        search_type=SearchType.hybrid,
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    print("\n" + "=" * 60)
    print("TopK: Vector search")
    print("=" * 60 + "\n")

    knowledge_vector.insert(url=url)
    agent_vector = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge_vector,
        search_knowledge=True,
        markdown=True,
    )
    agent_vector.print_response("What Thai recipes do you know?", stream=True)

    print("\n" + "=" * 60)
    print("TopK: Keyword (BM25) search")
    print("=" * 60 + "\n")

    knowledge_keyword.insert(url=url)
    agent_keyword = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge_keyword,
        search_knowledge=True,
        markdown=True,
    )
    agent_keyword.print_response("What Thai desserts are available?", stream=True)

    print("\n" + "=" * 60)
    print("TopK: Hybrid search")
    print("=" * 60 + "\n")

    knowledge_hybrid.insert(url=url)
    agent_hybrid = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge_hybrid,
        search_knowledge=True,
        markdown=True,
    )
    agent_hybrid.print_response("How do I make Pad Thai?", stream=True)
