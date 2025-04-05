import os
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.docx import DocxKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"docx_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def get_test_data_dir():
    """Get the path to the test data directory."""
    return Path(__file__).parent / "data"


def test_docx_knowledge_base_directory(setup_vector_db):
    """Test loading a directory of DOCX files into the knowledge base."""
    docx_dir = get_test_data_dir()

    kb = DocxKnowledgeBase(path=docx_dir, vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What is the story of little prince about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_docx_knowledge_base_single_file(setup_vector_db):
    """Test loading a single DOCX file into the knowledge base."""
    docx_file = get_test_data_dir() / "sample.docx"

    kb = DocxKnowledgeBase(path=docx_file, vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What is the story of little prince about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_docx_knowledge_base_async_directory(setup_vector_db):
    """Test asynchronously loading a directory of DOCX files into the knowledge base."""
    docx_dir = get_test_data_dir()

    kb = DocxKnowledgeBase(path=docx_dir, vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun("What is the story of little prince about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    # For async operations, we use async_search_knowledge_base
    assert any(call["function"]["name"] == "async_search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_docx_knowledge_base_async_single_file(setup_vector_db):
    """Test asynchronously loading a single DOCX file into the knowledge base."""
    docx_file = get_test_data_dir() / "sample.docx"

    kb = DocxKnowledgeBase(path=docx_file, vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun("What is the story of little prince about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    # For async operations, we use async_search_knowledge_base
    assert any(call["function"]["name"] == "async_search_knowledge_base" for call in function_calls)
