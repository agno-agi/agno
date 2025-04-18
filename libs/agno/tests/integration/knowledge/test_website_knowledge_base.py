import os

import pytest

from agno.agent import Agent
from agno.knowledge.website import WebsiteKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"website_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def test_website_knowledge_base_directory(setup_vector_db):
    """Test loading multiple websites into the knowledge base."""
    urls = ["https://docs.agno.com/introduction/agents", "https://docs.agno.com/introduction/playground"]

    kb = WebsiteKnowledgeBase(urls=urls, max_links=1, vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 5

    agent = Agent(knowledge=kb)
    response = agent.run("What are agents in Agno and what levels are there?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_website_knowledge_base_single_url(setup_vector_db):
    """Test loading a single website into the knowledge base."""
    kb = WebsiteKnowledgeBase(
        urls=["https://docs.agno.com/introduction/agents"], max_links=1, vector_db=setup_vector_db
    )
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 4

    agent = Agent(knowledge=kb)
    response = agent.run("How do I create a basic agent in Agno?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_website_knowledge_base_async_directory(setup_vector_db):
    """Test asynchronously loading multiple websites into the knowledge base."""
    urls = ["https://docs.agno.com/introduction/agents", "https://docs.agno.com/introduction/playground"]

    kb = WebsiteKnowledgeBase(urls=urls, max_links=1, vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 5

    agent = Agent(
        knowledge=kb,
        search_knowledge=True,
    )
    response = await agent.arun("What are agents in Agno and what levels are there?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    assert "async_search_knowledge_base" in [
        call["function"]["name"] for call in tool_calls if call.get("type") == "function"
    ]


@pytest.mark.asyncio
async def test_website_knowledge_base_async_single_url(setup_vector_db):
    """Test asynchronously loading a single website into the knowledge base."""
    kb = WebsiteKnowledgeBase(
        urls=["https://docs.agno.com/introduction/agents"], max_links=1, vector_db=setup_vector_db
    )
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 4

    agent = Agent(
        knowledge=kb,
        search_knowledge=True,
    )
    response = await agent.arun("How do I create a basic agent in Agno?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    assert "async_search_knowledge_base" in [
        call["function"]["name"] for call in tool_calls if call.get("type") == "function"
    ]
