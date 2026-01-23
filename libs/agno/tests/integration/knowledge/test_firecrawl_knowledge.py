import os

import pytest

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.firecrawl_reader import FirecrawlReader
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"firecrawl_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


@pytest.mark.skip(reason="Skipping firecrawl knowledge base tests")
def test_firecrawl_knowledge_base_directory(setup_vector_db):
    """Test loading multiple URLs into knowledge base"""
    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert_many(
        urls=["https://docs.agno.com/knowledge/introduction", "https://docs.agno.com/knowledge/pdf"],
        reader=FirecrawlReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb)
    response = agent.run("What is knowledge in Agno and what types are available?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.skip(reason="Skipping firecrawl knowledge base tests")
def test_firecrawl_knowledge_base_single_url(setup_vector_db):
    """Test loading a single URL into knowledge base"""
    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert_many(
        urls=["https://docs.agno.com/knowledge/pdf"],
        reader=FirecrawlReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb)
    response = agent.run("How do I use Knowledge in Agno?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.skip(reason="Skipping firecrawl knowledge base tests")
@pytest.mark.asyncio
async def test_firecrawl_knowledge_base_async_directory(setup_vector_db):
    """Test async loading of multiple URLs into knowledge base"""
    kb = Knowledge(vector_db=setup_vector_db)
    await kb.ainsert_many(
        urls=["https://docs.agno.com/knowledge/introduction", "https://docs.agno.com/knowledge/pdf"],
        reader=FirecrawlReader(),
    )

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun(
        "What are the different types of knowledge bases available in Agno and how do I use PDF knowledge base?",
        markdown=True,
    )

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.skip(reason="Skipping firecrawl knowledge base tests")
@pytest.mark.asyncio
async def test_firecrawl_knowledge_base_async_single_url(setup_vector_db):
    """Test async loading of a single URL into knowledge base"""
    kb = Knowledge(vector_db=setup_vector_db)
    await kb.ainsert_many(
        urls=["https://docs.agno.com/knowledge/introduction"],
        reader=FirecrawlReader(),
    )

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    agent = Agent(knowledge=kb)
    response = await agent.arun("What is a knowledge base in Agno?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.skip(reason="Skipping firecrawl knowledge base tests")
def test_firecrawl_knowledge_base_empty_urls(setup_vector_db):
    """Test handling of empty URL list"""
    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert_many(
        urls=[],
        reader=FirecrawlReader(),
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0
