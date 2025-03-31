import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.document import Document
from agno.document.reader.text_reader import TextReader
from agno.knowledge.text import TextKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_test_data():
    """Create temporary text files for testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create the main directory
        data_dir = Path(temp_dir) / "data" / "text"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Create a single text file
        sample_file_path = data_dir / "sample.txt"
        with open(sample_file_path, "w") as f:
            f.write("This is a sample text file.\nIt contains multiple lines.\nTo test text knowledge base.")

        subdirectory = data_dir / "subdirectory"
        subdirectory.mkdir(exist_ok=True)

        file1_path = subdirectory / "file1.txt"
        with open(file1_path, "w") as f:
            f.write("This is the first file in the subdirectory.\nIt talks about language models.")

        file2_path = subdirectory / "file2.txt"
        with open(file2_path, "w") as f:
            f.write("This is the second file in the subdirectory.\nIt discusses vector embeddings.")

        non_text_path = subdirectory / "document.pdf"
        with open(non_text_path, "w") as f:
            f.write("This is not a text file and should be ignored by the reader.")

        yield temp_dir


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"text_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


@pytest.fixture
def mock_text_documents():
    """Create mock documents that would be returned by the text reader."""
    return [
        Document(
            name="sample.txt",
            id="sample_txt",
            content="This is a sample text file. It contains multiple lines. To test text knowledge base.",
            meta_data={"path": "/data/text/sample.txt"},
        )
    ]


@pytest.fixture
def mock_additional_documents():
    """Create mock documents for additional files."""
    return [
        Document(
            name="file1.txt",
            id="file1_txt",
            content="This is the first file in the subdirectory. It talks about language models.",
            meta_data={"path": "/data/text/subdirectory/file1.txt"},
        ),
        Document(
            name="file2.txt",
            id="file2_txt",
            content="This is the second file in the subdirectory. It discusses vector embeddings.",
            meta_data={"path": "/data/text/subdirectory/file2.txt"},
        ),
    ]


def test_text_knowledge_base_directory(setup_test_data, setup_vector_db):
    """Test loading a directory of text files into the knowledge base."""
    text_dir = Path(setup_test_data) / "data" / "text"

    kb = TextKnowledgeBase(path=text_dir, formats=[".txt"], vector_db=setup_vector_db)

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 3

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = agent.run("Tell me about vector embeddings", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_text_knowledge_base_single_file(setup_test_data, setup_vector_db):
    """Test loading a single text file into the knowledge base."""
    text_file = Path(setup_test_data) / "data" / "text" / "sample.txt"

    kb = TextKnowledgeBase(path=text_file, formats=[".txt"], vector_db=setup_vector_db)

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 1

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = agent.run("What does the sample file contain?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


def test_text_knowledge_base_with_mocked_reader(setup_vector_db, mock_text_documents, mock_additional_documents):
    """Test with mocked text reader to ensure proper integration."""
    mock_reader = MagicMock(spec=TextReader)

    def mock_read(file):
        if "sample.txt" in str(file):
            return mock_text_documents
        else:
            return mock_additional_documents

    mock_reader.read.side_effect = mock_read

    with tempfile.NamedTemporaryFile(suffix=".txt") as sample_file:
        sample_file.write(b"Sample text content")
        sample_file.flush()
        sample_path = Path(sample_file.name)

        kb = TextKnowledgeBase(path=sample_path, formats=[".txt"], vector_db=setup_vector_db, reader=mock_reader)

        kb.load(recreate=True)

        assert setup_vector_db.exists()
        assert setup_vector_db.get_count() > 0
        assert mock_reader.read.call_count > 0


def test_text_knowledge_base_unsupported_format(setup_test_data, setup_vector_db):
    """Test that unsupported file formats are correctly filtered out."""
    text_dir = Path(setup_test_data) / "data" / "text"

    kb = TextKnowledgeBase(path=text_dir, formats=[".md"], vector_db=setup_vector_db)

    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0


def test_text_knowledge_base_nonexistent_path(setup_vector_db):
    """Test behavior with a non-existent path."""
    kb = TextKnowledgeBase(path="/path/that/does/not/exist", formats=[".txt"], vector_db=setup_vector_db)

    kb.load(recreate=True)
    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() == 0


@pytest.mark.asyncio
async def test_text_knowledge_base_async_directory(setup_test_data, setup_vector_db):
    """Test asynchronously loading a directory of text files into the knowledge base."""
    text_dir = Path(setup_test_data) / "data" / "text"

    kb = TextKnowledgeBase(path=text_dir, formats=[".txt"], vector_db=setup_vector_db)

    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 3

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = await agent.arun("Tell me about language models", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_text_knowledge_base_async_single_file(setup_test_data, setup_vector_db):
    """Test asynchronously loading a single text file into the knowledge base."""
    text_file = Path(setup_test_data) / "data" / "text" / "sample.txt"

    # Create the knowledge base
    kb = TextKnowledgeBase(path=text_file, formats=[".txt"], vector_db=setup_vector_db)

    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() == 1

    from agno.agent import Agent

    agent = Agent(knowledge=kb)

    response = await agent.arun("What does the sample file contain?", markdown=True)

    # Verify the agent used the knowledge base
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    # Check if any function call is to search_knowledge_base
    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_text_knowledge_base_async_with_mocked_reader(
    setup_vector_db, mock_text_documents, mock_additional_documents
):
    """Test async functionality with mocked text reader to ensure proper integration."""
    mock_reader = MagicMock(spec=TextReader)
    mock_reader.async_read = AsyncMock()

    async def mock_async_read(file):
        if "sample.txt" in str(file):
            return mock_text_documents
        else:
            return mock_additional_documents

    mock_reader.async_read.side_effect = mock_async_read

    with tempfile.NamedTemporaryFile(suffix=".txt") as sample_file:
        sample_file.write(b"Sample text content")
        sample_file.flush()
        sample_path = Path(sample_file.name)

        kb = TextKnowledgeBase(path=sample_path, formats=[".txt"], vector_db=setup_vector_db, reader=mock_reader)

        await kb.aload(recreate=True)

        assert await setup_vector_db.async_exists()
        assert await setup_vector_db.async_get_count() > 0

        assert mock_reader.async_read.call_count > 0
