import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.document import Document
from agno.document.reader.website_reader import WebsiteReader
from agno.knowledge.website import WebsiteKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def mock_website_content():
    return [
        Document(
            name="https://example.com/page1",
            id="example_page1",
            content="This is an example webpage about machine learning concepts.",
            meta_data={"url": "https://example.com/page1", "depth": 0},
        ),
        Document(
            name="https://example.com/page2",
            id="example_page2",
            content="Deep learning is a subset of machine learning.",
            meta_data={"url": "https://example.com/page2", "depth": 1},
        ),
    ]


@pytest.fixture
def mock_additional_website():
    return [
        Document(
            name="https://example.org/page1",
            id="example_org_page1",
            content="Natural language processing uses AI to understand human language.",
            meta_data={"url": "https://example.org/page1", "depth": 0},
        ),
        Document(
            name="https://example.org/page2",
            id="example_org_page2",
            content="Computer vision is another important area of AI research.",
            meta_data={"url": "https://example.org/page2", "depth": 1},
        ),
        Document(
            name="https://example.org/page3",
            id="example_org_page3",
            content="Reinforcement learning is about training agents through rewards.",
            meta_data={"url": "https://example.org/page3", "depth": 1},
        ),
    ]


@pytest.fixture
def setup_vector_db():
    # Create a unique table name for each test to avoid conflicts
    table_name = f"website_test_{uuid.uuid4().hex[:8]}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def test_website_knowledge_base(mock_website_content, mock_additional_website, setup_vector_db):
    # Setup mocked WebsiteReader
    mock_reader = MagicMock(spec=WebsiteReader)
    mock_reader.read.side_effect = [mock_website_content, mock_additional_website]

    # Create WebsiteKnowledgeBase instance
    kb = WebsiteKnowledgeBase(
        urls=["https://example.com", "https://example.org"], vector_db=setup_vector_db, reader=mock_reader
    )

    # Load the knowledge base
    kb.load(recreate=True)

    # Verify the knowledge base was loaded correctly
    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 5

    # Test querying the knowledge base via the agent
    from agno.agent import Agent

    # Initialize the agent with the knowledge base
    agent = Agent(knowledge=kb)

    # Run a query
    response = agent.run("Tell me about machine learning.", markdown=True)

    # Verify the agent used the knowledge base by checking tool calls
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    # Check if any function call is to search_knowledge_base
    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_website_knowledge_base_single_url(mock_website_content, setup_vector_db):
    # Setup mocked WebsiteReader
    mock_reader = MagicMock(spec=WebsiteReader)
    mock_reader.read.return_value = mock_website_content

    # Create WebsiteKnowledgeBase instance with a single URL
    kb = WebsiteKnowledgeBase(urls=["https://example.com"], vector_db=setup_vector_db, reader=mock_reader)

    # Load the knowledge base
    kb.load(recreate=True)

    # Verify the knowledge base was loaded correctly
    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 2

    # Test querying the knowledge base via the agent
    from agno.agent import Agent

    # Initialize the agent with the knowledge base
    agent = Agent(knowledge=kb)

    # Run a query
    response = agent.run("What is deep learning?", markdown=True)

    # Verify the agent used the knowledge base by checking tool calls
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    # Check if any function call is to search_knowledge_base
    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_website_knowledge_base_async(mock_website_content, mock_additional_website, setup_vector_db):
    # Setup mocked WebsiteReader
    mock_reader = MagicMock(spec=WebsiteReader)
    mock_reader.async_read = AsyncMock()
    mock_reader.async_read.side_effect = [mock_website_content, mock_additional_website]

    # Create WebsiteKnowledgeBase instance
    kb = WebsiteKnowledgeBase(
        urls=["https://example.com", "https://example.org"], vector_db=setup_vector_db, reader=mock_reader
    )

    # Load the knowledge base asynchronously
    await kb.async_load(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 5

    # Test querying the knowledge base via the agent
    from agno.agent import Agent

    # Initialize the agent with the knowledge base
    agent = Agent(knowledge=kb)

    # Run a query asynchronously
    response = await agent.arun("Tell me about natural language processing.", markdown=True)

    # Verify the agent used the knowledge base by checking tool calls
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    # Check if any function call is to search_knowledge_base
    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)

    # Check if relevant content is in the response
    assert "Natural language processing" in response.content or "language" in response.content


@pytest.mark.asyncio
async def test_website_knowledge_base_async_single_url(mock_website_content, setup_vector_db):
    # Setup mocked WebsiteReader
    mock_reader = MagicMock(spec=WebsiteReader)
    mock_reader.async_read = AsyncMock(return_value=mock_website_content)

    # Create WebsiteKnowledgeBase instance with a single URL
    kb = WebsiteKnowledgeBase(urls=["https://example.com"], vector_db=setup_vector_db, reader=mock_reader)

    # Load the knowledge base asynchronously
    await kb.async_load(recreate=True)

    assert await setup_vector_db.async_exists()

    assert await setup_vector_db.async_get_count() == 2

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    # Run a query asynchronously
    response = await agent.arun("What is machine learning?", markdown=True)

    # Verify the agent used the knowledge base by checking tool calls
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    # Check if any function call is to search_knowledge_base
    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_website_knowledge_base_skip_existing(mock_website_content, setup_vector_db):
    mock_reader = MagicMock(spec=WebsiteReader)
    mock_reader.read.return_value = mock_website_content

    kb = WebsiteKnowledgeBase(urls=["https://example.com"], vector_db=setup_vector_db, reader=mock_reader)

    # Load the knowledge base
    kb.load(recreate=True)

    # Verify first load
    assert setup_vector_db.get_count() == 2

    with patch.object(setup_vector_db, "name_exists", return_value=True):
        kb.load(recreate=False)

        assert setup_vector_db.get_count() == 2
        assert mock_reader.read.call_count == 1


@pytest.mark.asyncio
async def test_website_knowledge_base_async_skip_existing(mock_website_content, setup_vector_db):
    # Setup mocked WebsiteReader
    mock_reader = MagicMock(spec=WebsiteReader)
    mock_reader.async_read = AsyncMock(return_value=mock_website_content)

    # Create WebsiteKnowledgeBase instance
    kb = WebsiteKnowledgeBase(urls=["https://example.com"], vector_db=setup_vector_db, reader=mock_reader)

    await kb.async_load(recreate=True)
    assert await setup_vector_db.async_get_count() == 2

    setup_vector_db.async_name_exists = AsyncMock(return_value=True)

    await kb.async_load(recreate=False)
    assert await setup_vector_db.async_get_count() == 2
    assert mock_reader.async_read.call_count == 1


def test_auto_initialize_reader():
    """Test that a reader is automatically initialized if not provided"""
    kb = WebsiteKnowledgeBase(urls=["https://example.com"], max_depth=2, max_links=5)

    assert kb.reader is not None
    assert isinstance(kb.reader, WebsiteReader)
    assert kb.reader.max_depth == 2
    assert kb.reader.max_links == 5
