"""This cookbook shows how to add content from multiple paths and URLs to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/04_from_multiple.py` to run the cookbook
"""

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
    ),
)

# As a list
knowledge.add_contents(
    [
        {
            "name": "CV's",
            "path": "cookbook/knowledge/testing_resources/cv_1.pdf",
            "metadata": {"user_tag": "Engineering candidates"},
        },
        {
            "name": "Docs",
            "url": "https://docs.agno.com/introduction",
            "metadata": {"user_tag": "Documents"},
        },
    ]
)

# Using specifc fields
knowledge.add_contents(
    urls=[
        "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        "https://docs.agno.com/introduction",
        "https://docs.agno.com/basics/knowledge/overview.md",
    ],
)

agent = Agent(knowledge=knowledge)

agent.print_response("What can you tell me about Agno?", markdown=True)
