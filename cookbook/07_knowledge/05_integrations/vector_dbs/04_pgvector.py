"""
PgVector: PostgreSQL Vector Search
====================================
PgVector adds vector similarity search to PostgreSQL, giving you
vectors alongside your existing relational data in one database.

Features:
- Vector, keyword, and hybrid search
- Full SQL capabilities for complex queries
- HNSW and IVFFlat indexing
- Reranking support
- Battle-tested PostgreSQL reliability

Setup: ./cookbook/scripts/run_pgvector.sh
Requires: pip install pgvector psycopg[binary]

See also: 01_qdrant.py for recommended default, 02_local.py for local dev.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# --- Basic PgVector setup ---
knowledge_basic = Knowledge(
    vector_db=PgVector(
        table_name="pgvector_basic",
        db_url=db_url,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# --- Hybrid search with reranking ---
knowledge_hybrid = Knowledge(
    vector_db=PgVector(
        table_name="pgvector_hybrid",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        reranker=CohereReranker(model="rerank-multilingual-v3.0"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    # --- Basic vector search ---
    print("\n" + "=" * 60)
    print("PgVector: Basic vector search")
    print("=" * 60 + "\n")

    knowledge_basic.insert(url=pdf_url)
    agent = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge_basic,
        search_knowledge=True,
        markdown=True,
    )
    agent.print_response("What Thai recipes do you know?", stream=True)

    # --- Hybrid search with reranking ---
    print("\n" + "=" * 60)
    print("PgVector: Hybrid search + Cohere reranking")
    print("=" * 60 + "\n")

    knowledge_hybrid.insert(url=pdf_url)
    agent_hybrid = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge_hybrid,
        search_knowledge=True,
        markdown=True,
    )
    agent_hybrid.print_response("What Thai desserts are available?", stream=True)
