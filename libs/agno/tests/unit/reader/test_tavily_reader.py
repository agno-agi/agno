from unittest.mock import patch

import pytest

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.document.base import Document
from agno.knowledge.reader.tavily_reader import TavilyReader


@pytest.fixture
def mock_extract_response():
    """Mock response for extract method"""
    return {
        "results": [
            {
                "url": "https://example.com",
                "raw_content": "# Test Website\n\nThis is test content from an extracted website.",
            }
        ]
    }


@pytest.fixture
def mock_extract_multiple_response():
    """Mock response for multiple URL extraction"""
    return {
        "results": [
            {
                "url": "https://example1.com",
                "raw_content": "# Page 1\n\nThis is content from page 1.",
            },
            {
                "url": "https://example2.com",
                "raw_content": "# Page 2\n\nThis is content from page 2.",
            },
        ]
    }


def test_extract_basic(mock_extract_response):
    """Test basic extraction functionality"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = mock_extract_response

        # Create reader and call read (public API)
        reader = TavilyReader()
        reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
        documents = reader.read("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].id == "https://example.com_1"
        # Content is joined with spaces instead of newlines
        expected_content = "# Test Website This is test content from an extracted website."
        assert documents[0].content == expected_content

        # Verify TavilyClient was called correctly
        MockTavilyClient.assert_called_once_with(api_key=None)
        mock_client.extract.assert_called_once()
        call_args = mock_client.extract.call_args[1]
        assert call_args["urls"] == ["https://example.com"]
        assert call_args["depth"] == "basic"


def test_extract_with_api_key_and_params():
    """Test extraction with API key and custom parameters"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {"results": [{"url": "https://example.com", "raw_content": "Test content"}]}

        # Create reader with API key and params
        api_key = "test_api_key"
        params = {"include_images": True}
        reader = TavilyReader(api_key=api_key, params=params)
        reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
        reader.read("https://example.com")

        # Verify TavilyClient was called with correct parameters
        MockTavilyClient.assert_called_once_with(api_key=api_key)
        call_args = mock_client.extract.call_args[1]
        assert call_args.get("include_images") is True


def test_extract_with_advanced_depth():
    """Test extraction with advanced depth parameter"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {"results": [{"url": "https://example.com", "raw_content": "Test content"}]}

        # Create reader with advanced depth
        reader = TavilyReader(extract_depth="advanced")
        reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
        reader.read("https://example.com")

        # Verify advanced depth was used
        call_args = mock_client.extract.call_args[1]
        assert call_args["depth"] == "advanced"


def test_extract_empty_response():
    """Test handling of empty response from extract"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock for empty response
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {}

        # Create reader and call read
        reader = TavilyReader()
        documents = reader.read("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].content == ""


def test_extract_no_results():
    """Test handling of response with no results"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock for empty results
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {"results": []}

        # Create reader and call read
        reader = TavilyReader()
        documents = reader.read("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].content == ""


def test_extract_none_content():
    """Test handling of None content from extract"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock for None content
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {
            "results": [
                {
                    "url": "https://example.com",
                    "raw_content": None,
                }
            ]
        }

        # Create reader and call read
        reader = TavilyReader()
        documents = reader.read("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].content == ""


def test_extract_failed_extraction():
    """Test handling of failed extraction"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock for failed extraction
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {
            "results": [
                {
                    "url": "https://example.com",
                    "failed_reason": "Page not found",
                }
            ]
        }

        # Create reader and call read
        reader = TavilyReader()
        documents = reader.read("https://example.com")

        # Verify results - should return empty document
        assert len(documents) == 1
        assert documents[0].content == ""


def test_extract_with_chunking(mock_extract_response):
    """Test extraction with chunking enabled"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = mock_extract_response

        # Create reader with chunking enabled
        reader = TavilyReader()
        reader.chunk = True
        reader.chunking_strategy = FixedSizeChunking(chunk_size=10)  # Small chunk size to ensure multiple chunks

        # Create a patch for chunk_document
        def mock_chunk_document(doc):
            # Simple mock that splits into 2 chunks
            return [
                doc,  # Original document
                Document(
                    name=doc.name,
                    id=f"{doc.id}_chunk",
                    content="Chunked content",
                ),
            ]

        with patch.object(reader, "chunk_document", side_effect=mock_chunk_document):
            # Call read
            documents = reader.read("https://example.com")

            # Verify results
            assert len(documents) == 2
            assert documents[0].name == "https://example.com"
            assert documents[1].id == "https://example.com_chunk"


def test_extract_exception_handling():
    """Test handling of exceptions during extraction"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock to raise exception
        mock_client = MockTavilyClient.return_value
        mock_client.extract.side_effect = Exception("API Error")

        # Create reader and call read
        reader = TavilyReader()
        documents = reader.read("https://example.com")

        # Verify results - should return empty document
        assert len(documents) == 1
        assert documents[0].content == ""


def test_read_method(mock_extract_response):
    """Test read method calls extract"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = mock_extract_response

        reader = TavilyReader()
        reader.chunking_strategy = FixedSizeChunking(chunk_size=100)
        documents = reader.read("https://example.com")

        assert len(documents) == 1
        expected_content = "# Test Website This is test content from an extracted website."
        assert documents[0].content == expected_content

        mock_client.extract.assert_called_once()


def test_extract_with_custom_name():
    """Test extraction with custom document name"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyClient") as MockTavilyClient:
        # Set up mock
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = {
            "results": [
                {
                    "url": "https://example.com",
                    "raw_content": "Test content",
                }
            ]
        }

        # Create reader and call read with custom name
        reader = TavilyReader(chunk=False)
        documents = reader.read("https://example.com", name="Custom Name")

        # Verify custom name was used
        assert documents[0].name == "Custom Name"
        assert documents[0].id == "https://example.com"


@pytest.mark.asyncio
async def test_async_extract_basic(mock_extract_response):
    """Test basic async extraction functionality"""
    with patch("asyncio.to_thread") as mock_to_thread, patch("tavily.TavilyClient") as MockTavilyClient:
        # Configure mock to return the expected result
        mock_client = MockTavilyClient.return_value
        mock_client.extract.return_value = mock_extract_response

        # Make to_thread return a document directly to avoid actual thread execution
        document = Document(
            name="https://example.com",
            id="https://example.com_1",
            content="# Test Website\n\nThis is test content from an extracted website.",
        )
        mock_to_thread.return_value = [document]

        reader = TavilyReader()
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].id == "https://example.com_1"
        assert documents[0].content == "# Test Website\n\nThis is test content from an extracted website."

        # Verify to_thread was called with the right arguments
        mock_to_thread.assert_called_once()


@pytest.mark.asyncio
async def test_async_read(mock_extract_response):
    """Test async_read method calls _async_extract"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyReader._async_extract") as mock_async_extract:
        # Create a document to return
        document = Document(
            name="https://example.com",
            id="https://example.com_1",
            content="# Test Website\n\nThis is test content from an extracted website.",
        )
        mock_async_extract.return_value = [document]

        reader = TavilyReader()
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 1
        assert documents[0].content == "# Test Website\n\nThis is test content from an extracted website."

        # Verify _async_extract was called
        mock_async_extract.assert_called_once_with("https://example.com", None)


@pytest.mark.asyncio
async def test_async_read_with_custom_name():
    """Test async_read method with custom name"""
    with patch("agno.knowledge.reader.tavily_reader.TavilyReader._async_extract") as mock_async_extract:
        # Create a document to return
        document = Document(
            name="Custom Name",
            id="https://example.com",
            content="Test content",
        )
        mock_async_extract.return_value = [document]

        reader = TavilyReader()
        documents = await reader.async_read("https://example.com", name="Custom Name")

        assert len(documents) == 1
        assert documents[0].name == "Custom Name"

        # Verify _async_extract was called with custom name
        mock_async_extract.assert_called_once_with("https://example.com", "Custom Name")


def test_extract_format_initialization():
    """Test that extract_format is properly initialized"""
    # Test default format
    reader1 = TavilyReader()
    assert reader1.extract_format == "markdown"

    # Test custom format
    reader2 = TavilyReader(extract_format="text")
    assert reader2.extract_format == "text"


def test_extract_depth_initialization():
    """Test that extract_depth is properly initialized"""
    # Test default depth
    reader1 = TavilyReader()
    assert reader1.extract_depth == "basic"

    # Test custom depth
    reader2 = TavilyReader(extract_depth="advanced")
    assert reader2.extract_depth == "advanced"


def test_supported_content_types():
    """Test that reader declares URL as supported content type"""
    from agno.knowledge.types import ContentType

    supported_types = TavilyReader.get_supported_content_types()
    assert ContentType.URL in supported_types


def test_supported_chunking_strategies():
    """Test that reader declares supported chunking strategies"""
    from agno.knowledge.chunking.strategy import ChunkingStrategyType

    supported_strategies = TavilyReader.get_supported_chunking_strategies()

    # Verify all expected strategies are supported
    assert ChunkingStrategyType.CODE_CHUNKER in supported_strategies
    assert ChunkingStrategyType.SEMANTIC_CHUNKER in supported_strategies
    assert ChunkingStrategyType.FIXED_SIZE_CHUNKER in supported_strategies
    assert ChunkingStrategyType.AGENTIC_CHUNKER in supported_strategies
    assert ChunkingStrategyType.DOCUMENT_CHUNKER in supported_strategies
    assert ChunkingStrategyType.RECURSIVE_CHUNKER in supported_strategies
