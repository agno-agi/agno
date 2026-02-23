"""
PgVector: Production-Ready Vector Database
============================================
PgVector is the recommended vector database for production use.
Built on PostgreSQL, it provides reliable, scalable vector search
with full SQL capabilities.

Features:
- Vector, keyword, and hybrid search
- Reranking support
- Similarity threshold filtering
- Full PostgreSQL ecosystem (backups, replication, monitoring)

Setup: ./cookbook/scripts/run_pgvector.sh

See also: 02_local.py for local development, 03_managed.py for managed cloud.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

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
knowledge_advanced = Knowledge(
    vector_db=PgVector(
        table_name="pgvector_advanced",
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
    # --- Basic vector search ---
    print("\n" + "=" * 60)
    print("PgVector: Basic vector search")
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
    print("PgVector: Hybrid search + Cohere reranking")
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
