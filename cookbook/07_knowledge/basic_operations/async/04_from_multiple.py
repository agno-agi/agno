"""This cookbook shows how to add content from multiple paths and URLs to the knowledge base.
1. Run: `python cookbook/07_knowledge/basic_operations/async/04_from_multiple.py` to run the cookbook
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

# Create Knowledge Instance
knowledge = Knowledge(
    name="Basic SDK Knowledge Base",
    description="Agno 2.0 Knowledge Implementation",
    vector_db=PgVector(
        table_name="vectors",
        db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
        embedder=OpenAIEmbedder(),
    ),
)


async def main():
    # As a list
    await knowledge.ainsert_many(
        [
            {
                "name": "CV's",
                "path": "cookbook/07_knowledge/testing_resources/cv_1.pdf",
                "metadata": {"user_tag": "Engineering candidates"},
            },
            {
                "name": "Docs",
                "url": "https://docs.agno.com/introduction",
                "metadata": {"user_tag": "Documents"},
            },
        ]
    )

    # Using specific fields
    await knowledge.ainsert_many(
        urls=[
            "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            "https://docs.agno.com/introduction",
            "https://docs.agno.com/knowledge/overview.md",
        ],
    )


asyncio.run(main())

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"), knowledge=knowledge, search_knowledge=True
)

agent.print_response("What can you tell me about my documents?", markdown=True)
