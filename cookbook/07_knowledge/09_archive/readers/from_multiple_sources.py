"""
From Multiple Sources
=====================

Demonstrates loading knowledge from multiple paths and URLs using sync and async operations.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
def create_sync_knowledge() -> Knowledge:
    return Knowledge(
        name="Basic SDK Knowledge Base",
        description="Agno 2.0 Knowledge Implementation",
        vector_db=PgVector(
            table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
        ),
    )


def create_async_knowledge() -> Knowledge:
    return Knowledge(
        name="Basic SDK Knowledge Base",
        description="Agno 2.0 Knowledge Implementation",
        vector_db=PgVector(
            table_name="vectors",
            db_url="postgresql+psycopg://ai:ai@localhost:5532/ai",
            embedder=OpenAIEmbedder(),
        ),
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
def create_sync_agent(knowledge: Knowledge) -> Agent:
    return Agent(knowledge=knowledge, search_knowledge=True)


def create_async_agent(knowledge: Knowledge) -> Agent:
    return Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=knowledge,
        search_knowledge=True,
    )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def run_sync() -> None:
    knowledge = create_sync_knowledge()

    knowledge.insert_many(
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

    knowledge.insert_many(
        urls=[
            "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            "https://docs.agno.com/introduction",
            "https://docs.agno.com/knowledge/overview.md",
        ],
    )

    agent = create_sync_agent(knowledge)
    agent.print_response("What can you tell me about Agno?", markdown=True)


async def run_async() -> None:
    knowledge = create_async_knowledge()

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

    await knowledge.ainsert_many(
        urls=[
            "https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf",
            "https://docs.agno.com/introduction",
            "https://docs.agno.com/knowledge/overview.md",
        ],
    )

    agent = create_async_agent(knowledge)
    agent.print_response("What can you tell me about my documents?", markdown=True)


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
