"""
Filtering: Metadata-Based Search Refinement
=============================================
Filters let you narrow search results based on document metadata.
This is essential for multi-user, multi-topic, or access-controlled systems.

Three approaches:
1. Dict filters: Simple key-value matching {"category": "recipes"}
2. FilterExpr: Powerful expressions with AND, OR, NOT, EQ, IN, GT, LT
3. Metadata at insert time: Tag documents for later filtering

See also: 05_agentic_filtering.py for agent-driven filter selection.
"""

from agno.agent import Agent
from agno.filters import AND, EQ, IN
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

knowledge = Knowledge(
    vector_db=PgVector(
        table_name="filtering_demo",
        db_url=db_url,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Insert documents with metadata for filtering
    knowledge.insert(
        name="Thai Recipes",
        url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        metadata={"cuisine": "thai", "category": "recipes"},
    )

    knowledge.insert(
        name="Company Info",
        text_content="Agno is an AI framework for building agents with knowledge.",
        metadata={"category": "docs", "topic": "agno"},
    )

    # --- 1. Dict filters: simple key-value matching ---
    print("\n" + "=" * 60)
    print("APPROACH 1: Dict filters")
    print("=" * 60 + "\n")

    agent_dict = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge,
        search_knowledge=True,
        knowledge_filters={"cuisine": "thai"},
        markdown=True,
    )
    agent_dict.print_response("What recipes do you know?", stream=True)

    # --- 2. FilterExpr: powerful filter expressions ---
    print("\n" + "=" * 60)
    print("APPROACH 2: FilterExpr")
    print("=" * 60 + "\n")

    agent_expr = Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge,
        search_knowledge=True,
        knowledge_filters=[
            AND(EQ("category", "recipes"), IN("cuisine", ["thai", "indian"]))
        ],
        markdown=True,
    )
    agent_expr.print_response("What recipes do you know?", stream=True)
