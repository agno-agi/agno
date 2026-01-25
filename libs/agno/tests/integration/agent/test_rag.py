# Create a knowledge base of PDFs from URLs
import asyncio

import pytest
import pytest_asyncio

from agno.agent.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai.chat import OpenAIChat
from agno.vectordb.lancedb.lance_db import LanceDb
from agno.vectordb.search import SearchType


# Add a session-scoped event loop fixture
@pytest_asyncio.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture()
async def loaded_knowledge_base():
    knowledge = Knowledge(
        vector_db=LanceDb(
            table_name="recipes",
            uri="tmp/lancedb",
            search_type=SearchType.vector,
            embedder=OpenAIEmbedder(),
        ),
    )
    await knowledge.ainsert(
        url="https://agno-public.s3.amazonaws.com/recipes/thai_recipes_short.pdf",
    )
    return knowledge


@pytest.mark.asyncio
async def test_add_knowledge_to_context(loaded_knowledge_base):
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        knowledge=loaded_knowledge_base,
        # Enable RAG by adding references from Knowledge to the user prompt.
        add_knowledge_to_context=True,
        # Set as False because Agents default to `search_knowledge=True`
        search_knowledge=False,
        markdown=True,
    )

    response = await agent.arun("How do I make chicken and galangal in coconut milk soup")
    assert response.content is not None
