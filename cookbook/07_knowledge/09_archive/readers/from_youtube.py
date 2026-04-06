"""
From YouTube
============

Demonstrates loading knowledge from a YouTube URL using sync and async inserts.
"""

import asyncio

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.pgvector import PgVector

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
vector_db = PgVector(
    table_name="vectors", db_url="postgresql+psycopg://ai:ai@localhost:5532/ai"
)


# ---------------------------------------------------------------------------
# Create Knowledge Base
# ---------------------------------------------------------------------------
def create_knowledge() -> Knowledge:
    return Knowledge(
        name="Basic SDK Knowledge Base",
        description="Agno 2.0 Knowledge Implementation",
        vector_db=vector_db,
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
def create_agent(knowledge: Knowledge) -> Agent:
    return Agent(
        name="My Agent",
        description="Agno 2.0 Agent Implementation",
        knowledge=knowledge,
        search_knowledge=True,
        debug_mode=True,
    )


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
def run_sync() -> None:
    knowledge = create_knowledge()
    knowledge.insert(
        name="Agents from Scratch",
        url="https://www.youtube.com/watch?v=nLkBNnnA8Ac",
        metadata={"user_tag": "Youtube video"},
    )

    agent = create_agent(knowledge)
    agent.print_response(
        "What can you tell me about the building agents?",
        markdown=True,
    )


async def run_async() -> None:
    knowledge = create_knowledge()
    await knowledge.ainsert(
        name="Agents from Scratch",
        url="https://www.youtube.com/watch?v=nLkBNnnA8Ac",
        metadata={"user_tag": "Youtube video"},
    )

    agent = create_agent(knowledge)
    agent.print_response(
        "What can you tell me about the building agents?",
        markdown=True,
    )


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
