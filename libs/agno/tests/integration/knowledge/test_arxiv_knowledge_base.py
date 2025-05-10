import uuid

import pytest

from agno.agent import Agent
from agno.document.reader.arxiv_reader import ArxivReader
from agno.knowledge.arxiv import ArxivKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"arxiv_test_{uuid.uuid4().hex[:8]}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def test_arxiv_knowledge_base_integration(setup_vector_db):
    """Integration test using real arXiv papers."""
    reader = ArxivReader()
    kb = ArxivKnowledgeBase(
        # "Attention Is All You Need" and "BERT" papers
        queries=["1706.03762", "1810.04805"],
        vector_db=setup_vector_db,
        reader=reader,
        max_results=1,  # Limit to exactly one result per query
    )

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    # Check that we have at least the papers we requested
    assert setup_vector_db.get_count() >= 2

    agent = Agent(knowledge=kb)
    response = agent.run("Explain the key concepts of transformer architecture", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_arxiv_knowledge_base_search_integration(setup_vector_db):
    """Integration test using real arXiv search query."""
    reader = ArxivReader()
    kb = ArxivKnowledgeBase(
        queries=["transformer architecture language models"],
        vector_db=setup_vector_db,
        reader=reader,
        max_results=3,  # Limit results for testing
    )

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    agent = Agent(knowledge=kb)
    response = agent.run("What are the recent developments in transformer models?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_arxiv_knowledge_base_async_integration(setup_vector_db):
    """Integration test using real arXiv papers with async loading."""
    reader = ArxivReader()
    kb = ArxivKnowledgeBase(
        # "GPT-3" and "AlphaFold" papers
        queries=["2005.14165", "2003.02645"],
        vector_db=setup_vector_db,
        reader=reader,
        max_results=1,  # Limit to exactly one result per query
    )

    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    # Check that we have at least the papers we requested
    assert await setup_vector_db.async_get_count() >= 2

    agent = Agent(
        knowledge=kb,
        search_knowledge=True,
        instructions=[
            "You are a helpful assistant that can answer questions.",
            "You can use the asearch_knowledge_base tool to search the knowledge base of journal articles for information.",
        ],
    )
    response = await agent.arun("What are the key capabilities of GPT-3?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "asearch_knowledge_base" for call in function_calls)


def test_arxiv_knowledge_base_empty_query_integration(setup_vector_db):
    """Integration test with empty query list."""
    reader = ArxivReader()
    kb = ArxivKnowledgeBase(
        queries=[],
        vector_db=setup_vector_db,
        reader=reader,
    )

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0
