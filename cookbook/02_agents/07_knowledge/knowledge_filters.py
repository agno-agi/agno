"""
Knowledge Filters
=============================

Filter knowledge base searches using static filters or agentic filters.

Static filters are set at agent creation time and apply to every search.
Agentic filters let the agent dynamically choose filter values at runtime.
"""

from agno.agent import Agent
from agno.filters import EQ
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
knowledge = Knowledge(
    vector_db=PgVector(
        table_name="recipes_filters_demo",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Create Agent With Static Filters
# ---------------------------------------------------------------------------
# Static filters: only retrieve documents matching these criteria
agent_static = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    # Use FilterExpr objects for type-safe filtering
    knowledge_filters=[EQ("cuisine", "thai")],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create Agent With Agentic Filters
# ---------------------------------------------------------------------------
# Agentic filters: the agent decides filter values dynamically
agent_agentic = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    search_knowledge=True,
    # Let the agent choose filter values based on the user's query
    enable_agentic_knowledge_filters=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    knowledge.insert(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

    print("--- Static filters (cuisine=thai) ---")
    agent_static.print_response(
        "What soup recipes do you have?",
        stream=True,
    )

    print("\n--- Agentic filters ---")
    agent_agentic.print_response(
        "Find me a Thai dessert recipe.",
        stream=True,
    )
