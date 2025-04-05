import os

import pytest

from agno.agent import Agent
from agno.knowledge.url import UrlKnowledge
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"url_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def test_url_knowledge_base_directory(setup_vector_db):
    """Test loading multiple URLs into knowledge base"""
    kb = UrlKnowledge(
        urls=["https://www.paulgraham.com/users.html", "https://www.paulgraham.com/read.html"],
        vector_db=setup_vector_db,
    )
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb)
    response = agent.run("What does paul graham mainly talk about in these essays", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_url_knowledge_base_single_url(setup_vector_db):
    """Test loading a single URL into knowledge base"""
    kb = UrlKnowledge(urls=["https://www.paulgraham.com/users.html"], vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb)
    response = agent.run("What does the Paul Graham explain about users in this essay?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_url_knowledge_base_async_directory(setup_vector_db):
    """Test async loading of multiple URLs into knowledge base"""
    kb = UrlKnowledge(
        urls=["https://www.paulgraham.com/users.html", "https://www.paulgraham.com/read.html"],
        vector_db=setup_vector_db,
    )
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun(
        "What does Paul Graham talk about reading and the role of users in these essays?", markdown=True
    )

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "async_search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_url_knowledge_base_async_single_url(setup_vector_db):
    """Test async loading of a single URL into knowledge base"""
    kb = UrlKnowledge(urls=["https://www.paulgraham.com/read.html"], vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    agent = Agent(knowledge=kb)
    response = await agent.arun("What does Paul Graham talk about reading in this essay?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "async_search_knowledge_base" for call in function_calls)


def test_url_knowledge_base_empty_urls(setup_vector_db):
    """Test handling of empty URL list"""
    kb = UrlKnowledge(urls=[], vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0


@pytest.mark.asyncio
async def test_url_knowledge_base_invalid_url(setup_vector_db):
    """Test handling of invalid URL"""
    kb = UrlKnowledge(urls=["https://invalid.agno.com/nonexistent"], vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 0
