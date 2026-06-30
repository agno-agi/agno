"""
Website Tools Knowledge
=============================

Demonstrates website tools knowledge.
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.tools.website import WebsiteTools
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

# Create PDF URL knowledge base
kb = Knowledge(
    vector_db=PgVector(
        table_name="documents",
        db_url=db_url,
    ),
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    kb.insert_many(
        urls=[
            "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            "https://docs.agno.com/introduction",
        ]
    )

    # Initialize the Agent with the combined knowledge base
    agent = Agent(
        knowledge=kb,
        search_knowledge=True,
        tools=[
            WebsiteTools(knowledge=kb)  # Set combined or website knowledge base
        ],
    )

    # Use the agent
    agent.print_response(
        "How do I get started on Mistral: https://docs.mistral.ai/getting-started/models/models_overview",
        markdown=True,
        stream=True,
    )
