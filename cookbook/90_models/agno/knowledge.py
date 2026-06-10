"""
Agno Gateway - knowledge (RAG)
==============================

Knowledge is model-agnostic, so it works unchanged through the gateway. The agent
retrieves from a vector store and grounds its answer in the retrieved content.

Run `./cookbook/scripts/run_pgvector.sh` to start Postgres, then
`uv pip install ddgs sqlalchemy pgvector pypdf` to install dependencies.

Requires:
- AGNO_API_KEY  (or a provider key for BYOK, e.g. OPENAI_API_KEY for "openai/...")
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.agno import Agno
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
# Add content to the knowledge base
knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

agent = Agent(
    model=Agno(id="openai/gpt-5.4"),
    knowledge=knowledge,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent.print_response("How to make Thai curry?")
