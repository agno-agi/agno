import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.document import Document
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


@pytest.fixture
def mock_arxiv_documents():
    """Create mock documents that would be returned by the Arxiv reader for a given query."""
    return [
        Document(
            name="Paper 1: Deep Learning",
            id="2101.00001",
            content="This paper discusses deep learning techniques for natural language processing.",
            meta_data={"authors": ["A. Smith", "B. Jones"], "year": "2021", "url": "https://arxiv.org/abs/2101.00001"},
        ),
        Document(
            name="Paper 2: Neural Networks",
            id="2101.00002",
            content="A comprehensive review of neural network architectures and their applications.",
            meta_data={
                "authors": ["C. Williams", "D. Brown"],
                "year": "2021",
                "url": "https://arxiv.org/abs/2101.00002",
            },
        ),
    ]


@pytest.fixture
def mock_additional_documents():
    """Create mock documents for a different query."""
    return [
        Document(
            name="Paper 3: Reinforcement Learning",
            id="2102.00001",
            content="An overview of recent advances in reinforcement learning.",
            meta_data={"authors": ["E. Davis", "F. Miller"], "year": "2021", "url": "https://arxiv.org/abs/2102.00001"},
        ),
        Document(
            name="Paper 4: Transformers",
            id="2102.00002",
            content="Transformer architectures for sequence-to-sequence learning tasks.",
            meta_data={
                "authors": ["G. Wilson", "H. Taylor"],
                "year": "2021",
                "url": "https://arxiv.org/abs/2102.00002",
            },
        ),
        Document(
            name="Paper 5: Graph Neural Networks",
            id="2102.00003",
            content="Graph neural networks for representing relational data.",
            meta_data={"authors": ["I. Moore", "J. Adams"], "year": "2021", "url": "https://arxiv.org/abs/2102.00003"},
        ),
    ]


def test_arxiv_knowledge_base(setup_vector_db):
    """Test loading multiple arxiv queries into the knowledge base."""
    # Setup mocked ArxivReader
    mock_reader = MagicMock(spec=ArxivReader)
    mock_reader.read.side_effect = [
        [Document(name="Paper: Deep Learning", id="2101.00001", content="Deep learning content")],
        [Document(name="Paper: NLP", id="2102.00001", content="NLP content")],
    ]

    # Create ArxivKnowledgeBase instance
    kb = ArxivKnowledgeBase(
        queries=["deep learning", "natural language processing"], vector_db=setup_vector_db, reader=mock_reader
    )

    # Load the knowledge base
    kb.load(recreate=True)

    # Verify the knowledge base was loaded correctly
    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 2  # Two papers from different queries

    # Test querying the knowledge base via the agent
    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = agent.run("Tell me about deep learning", markdown=True)

    # Verify the agent used the knowledge base
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_arxiv_knowledge_base_single_query(setup_vector_db):
    """Test loading a single arxiv query into the knowledge base."""
    mock_reader = MagicMock(spec=ArxivReader)
    mock_reader.read.return_value = [
        Document(name="Paper: Transformers", id="2102.00002", content="Transformer models content")
    ]

    kb = ArxivKnowledgeBase(queries=["transformers"], vector_db=setup_vector_db, reader=mock_reader)

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 1  # One paper from the query

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = agent.run("What are transformer models?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_arxiv_knowledge_base_with_mocked_reader(setup_vector_db, mock_arxiv_documents, mock_additional_documents):
    """Test with mocked arxiv reader to ensure proper integration."""
    mock_reader = MagicMock(spec=ArxivReader)

    # Set up the mock read method to return different documents for different queries
    def mock_read(query):
        if query == "deep learning":
            return mock_arxiv_documents
        else:
            return mock_additional_documents

    mock_reader.read.side_effect = mock_read

    # Create knowledge base with mock reader
    kb = ArxivKnowledgeBase(
        queries=["deep learning", "reinforcement learning"], vector_db=setup_vector_db, reader=mock_reader
    )

    # Load the knowledge base
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 5

    # Verify the document reader was used
    assert mock_reader.read.call_count == 2
    mock_reader.read.assert_any_call(query="deep learning")
    mock_reader.read.assert_any_call(query="reinforcement learning")


def test_arxiv_knowledge_base_empty_query(setup_vector_db):
    """Test behavior with an empty query list."""
    mock_reader = MagicMock(spec=ArxivReader)

    kb = ArxivKnowledgeBase(
        queries=[],  # Empty query list
        vector_db=setup_vector_db,
        reader=mock_reader,
    )

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0  # No documents should be loaded
    assert mock_reader.read.call_count == 0  # Reader should not be called


@pytest.mark.asyncio
async def test_arxiv_knowledge_base_async(setup_vector_db):
    """Test asynchronously loading multiple arxiv queries into the knowledge base."""
    mock_reader = MagicMock(spec=ArxivReader)
    mock_reader.async_read = AsyncMock()

    # Set up the async_read mock to return documents
    mock_reader.async_read.side_effect = [
        [Document(name="Paper: Deep Learning", id="2101.00001", content="Deep learning content")],
        [Document(name="Paper: NLP", id="2102.00001", content="NLP content")],
    ]

    kb = ArxivKnowledgeBase(
        queries=["deep learning", "natural language processing"], vector_db=setup_vector_db, reader=mock_reader
    )

    # Load the knowledge base asynchronously
    await kb.aload(recreate=True)

    # Verify the knowledge base was loaded correctly
    assert await setup_vector_db.async_exists()
    # Two papers from different queries
    assert await setup_vector_db.async_get_count() == 2

    # Test querying the knowledge base via the agent
    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = await agent.arun("Tell me about deep learning", markdown=True)

    # Verify the agent used the knowledge base
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_arxiv_knowledge_base_async_single_query(setup_vector_db):
    """Test asynchronously loading a single arxiv query into the knowledge base."""
    mock_reader = MagicMock(spec=ArxivReader)
    mock_reader.async_read = AsyncMock(
        return_value=[Document(name="Paper: Transformers", id="2102.00002", content="Transformer models content")]
    )

    kb = ArxivKnowledgeBase(queries=["transformers"], vector_db=setup_vector_db, reader=mock_reader)

    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 1  # One paper from the query

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = await agent.arun("What are transformer models?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_arxiv_knowledge_base_async_with_mocked_reader(
    setup_vector_db, mock_arxiv_documents, mock_additional_documents
):
    """Test async functionality with mocked arxiv reader to ensure proper integration."""
    mock_reader = MagicMock(spec=ArxivReader)
    mock_reader.async_read = AsyncMock()

    async def mock_async_read(query):
        if query == "deep learning":
            return mock_arxiv_documents
        else:
            return mock_additional_documents

    mock_reader.async_read.side_effect = mock_async_read

    kb = ArxivKnowledgeBase(
        queries=["deep learning", "reinforcement learning"], vector_db=setup_vector_db, reader=mock_reader
    )

    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 5

    assert mock_reader.async_read.call_count == 2
    mock_reader.async_read.assert_any_call(query="deep learning")
    mock_reader.async_read.assert_any_call(query="reinforcement learning")


@pytest.mark.asyncio
async def test_arxiv_knowledge_base_async_empty_query(setup_vector_db):
    """Test async behavior with an empty query list."""
    mock_reader = MagicMock(spec=ArxivReader)
    mock_reader.async_read = AsyncMock()

    kb = ArxivKnowledgeBase(
        queries=[],  # Empty query list
        vector_db=setup_vector_db,
        reader=mock_reader,
    )

    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 0  # No documents should be loaded
    assert mock_reader.async_read.call_count == 0
