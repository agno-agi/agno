import os
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.text import TextKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"text_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def get_test_data_dir():
    """Get the path to the test data directory."""
    return Path(__file__).parent / "data"


def test_text_knowledge_base_directory(setup_vector_db):
    """Test loading a directory of text files into the knowledge base."""
    text_dir = get_test_data_dir()

    kb = TextKnowledgeBase(path=text_dir, formats=[".txt"], vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    # pg_essay.txt is split into 14 documents
    assert setup_vector_db.get_count() == 14

    agent = Agent(knowledge=kb)
    response = agent.run("What are the key factors in doing great work?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_text_knowledge_base_single_file(setup_vector_db):
    """Test loading a single text file into the knowledge base."""
    text_file = get_test_data_dir() / "pg_essay.txt"

    kb = TextKnowledgeBase(path=text_file, formats=[".txt"], vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    # pg_essay.txt is split into 14 documents
    assert setup_vector_db.get_count() == 14

    agent = Agent(knowledge=kb)
    response = agent.run("What does Paul Graham say about curiosity?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_text_knowledge_base_async_directory(setup_vector_db):
    """Test asynchronously loading a directory of text files into the knowledge base."""
    text_dir = get_test_data_dir()

    kb = TextKnowledgeBase(path=text_dir, formats=[".txt"], vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    # pg_essay.txt is split into 14 documents
    assert await setup_vector_db.async_get_count() == 14

    agent = Agent(knowledge=kb)
    response = await agent.arun("What does Paul Graham say about great work?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "async_search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_text_knowledge_base_async_single_file(setup_vector_db):
    """Test asynchronously loading a single text file into the knowledge base."""
    text_file = get_test_data_dir() / "pg_essay.txt"  # Changed to use pg_essay.txt

    kb = TextKnowledgeBase(path=text_file, formats=[".txt"], vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    # pg_essay.txt is split into 14 documents
    assert await setup_vector_db.async_get_count() == 14

    agent = Agent(knowledge=kb)
    response = await agent.arun("What are the advantages of youth in doing great work?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "async_search_knowledge_base" for call in function_calls)
