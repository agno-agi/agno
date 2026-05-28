"""Run `uv pip install ddgs sqlalchemy pgvector pypdf llama-api-client` to install dependencies."""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.models.meta import Llama
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(table_name="recipes", db_url=db_url),
)
# Add content to the knowledge
knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

agent = Agent(
    model=Llama(id="Llama-4-Maverick-17B-128E-Instruct-FP8"), knowledge=knowledge
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Create and use the agent
    asyncio.run(agent.aprint_response("How to make Thai curry?", markdown=True))
