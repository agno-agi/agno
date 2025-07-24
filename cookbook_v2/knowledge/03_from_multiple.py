"""This cookbook shows how to add content from multiple paths and URLs to the knowledge base.
1. Run: `python cookbook/agent_concepts/knowledge/03_from_multiple.py` to run the cookbook
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

knowledge.add_contents(
    [
        {
            "name": "CV's",
            "path": "cookbook/agent_concepts/knowledge/testing_resources/",
            "metadata": {"user_tag": "Engineering candidates"},
        },
        {
            "name": "Docs",
            "path": "my_documents/",
            "metadata": {"user_tag": "Documents"},
        },
    ]
)

knowledge.add_contents(
    name="CV's",
    description="Engineering candidates",
    metadata={"user_tag": "Engineering candidates"},
    paths=["tmp/", "docs/"],
    urls=[
        "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
        "https://docs.agno.com/introduction",
        "https://docs.agno.com/agents/knowledge.md",
    ],
)

agent = Agent(knowledge=knowledge, show_tool_calls=True)

agent.print_response("What can you tell me about my documents?", markdown=True)
