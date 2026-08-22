"""
openGauss DataVec: Vector Search
====================================
openGauss DataVec brings vector search to openGauss so you can run
semantic retrieval with SQL in the same database stack.

Features:
- Vector, keyword, and hybrid search
- SQL + ANN retrieval in one system
- HNSW and IVFFlat indexing
- Compatible with openGauss DataVec deployments

Requires:
- pip install sqlalchemy pgvector psycopg[binary]
- openGauss 6.0.3+
- DataVec enabled in the target instance

See also: 04_pgvector.py for PostgreSQL pgvector integration.
"""

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.opengauss import OpenGaussVectorDb
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

# Example URL. Adjust host/port/user/password/database for your environment.
db_url = "postgresql+psycopg://gaussdb:gaussdb@localhost:5432/postgres"

# --- Basic vector search ---
knowledge_basic = Knowledge(
    vector_db=OpenGaussVectorDb(
        table_name="opengauss_datavec_basic",
        db_url=db_url,
        search_type=SearchType.vector,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# --- Hybrid search ---
knowledge_hybrid = Knowledge(
    vector_db=OpenGaussVectorDb(
        table_name="opengauss_datavec_hybrid",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    pdf_url = "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf"

    # --- Basic vector search ---
    print("\n" + "=" * 60)
    print("openGauss DataVec: Basic vector search")
    print("=" * 60 + "\n")

    knowledge_basic.insert(url=pdf_url)

    agent = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge_basic,
        search_knowledge=True,
        markdown=True,
    )
    agent.print_response("What Thai recipes do you know?", stream=True)

    # --- Hybrid search ---
    print("\n" + "=" * 60)
    print("openGauss DataVec: Hybrid search")
    print("=" * 60 + "\n")

    knowledge_hybrid.insert(url=pdf_url)

    agent_hybrid = Agent(
        model=OpenAIResponses(id="gpt-5.4"),
        knowledge=knowledge_hybrid,
        search_knowledge=True,
        markdown=True,
    )
    agent_hybrid.print_response("What Thai desserts are available?", stream=True)
