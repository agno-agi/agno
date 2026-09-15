"""
OracleVector: Oracle Database Vector Search
============================================
OracleVector adds vector similarity search to Oracle Database (23ai and
later), giving you vectors alongside your existing relational data in one
database.

Features:
- Vector, keyword, and hybrid search
- Oracle Text (CTXSYS.CONTEXT) powers keyword relevance
- IVF (partition-based) and HNSW (in-memory graph) indexing
- Similarity thresholds to exclude weak matches
- Reranking support

Setup: ./cookbook/scripts/run_oracle.sh (use the 23ai+ image; vector search
requires Oracle Database 23ai or later, unlike storage, which works from 19c)
Requires: uv pip install "agno[oracle]"

Keyword and hybrid search need optimize() called once, explicitly, after the
knowledge base has content -- the knowledge layer never calls it for you. See
also: 01_qdrant.py for recommended default, 04_pgvector.py for the PostgreSQL
equivalent this store mirrors.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reranker.cohere import CohereReranker
from agno.models.openai import OpenAIResponses
from agno.vectordb.oracle import OracleVector
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Create Knowledge
# ---------------------------------------------------------------------------

db_url = "oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1"

# --- Basic vector search ---
vector_db_basic = OracleVector(
    table_name="oracle_vector_basic",
    db_url=db_url,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
)
knowledge_basic = Knowledge(vector_db=vector_db_basic)

# --- Hybrid search with reranking ---
vector_db_hybrid = OracleVector(
    table_name="oracle_vector_hybrid",
    db_url=db_url,
    search_type=SearchType.hybrid,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    reranker=CohereReranker(model="rerank-multilingual-v3.0"),
)
knowledge_hybrid = Knowledge(vector_db=vector_db_hybrid)

# --- Vector search with a similarity threshold ---
vector_db_threshold = OracleVector(
    table_name="oracle_vector_threshold",
    db_url=db_url,
    embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    similarity_threshold=0.5,
)
knowledge_threshold = Knowledge(vector_db=vector_db_threshold)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    # --- Basic vector search ---
    print("\n" + "=" * 60)
    print("OracleVector: Basic vector search")
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
    print("OracleVector: Hybrid search + Cohere reranking")
    print("=" * 60 + "\n")

    knowledge_hybrid.insert(url=pdf_url)
    # optimize() creates the ANN vector index and the Oracle Text CONTEXT index
    # hybrid/keyword search need; without it they fail with an actionable error.
    vector_db_hybrid.optimize()
    agent_hybrid = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge_hybrid,
        search_knowledge=True,
        markdown=True,
    )
    agent_hybrid.print_response("What Thai desserts are available?", stream=True)

    # --- Vector search with a similarity threshold ---
    print("\n" + "=" * 60)
    print("OracleVector: Vector search with a similarity threshold")
    print("=" * 60 + "\n")

    knowledge_threshold.insert(url=pdf_url)
    agent_threshold = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge_threshold,
        search_knowledge=True,
        markdown=True,
    )
    agent_threshold.print_response("What Thai desserts are available?", stream=True)
