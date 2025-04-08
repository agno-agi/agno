from unittest.mock import patch

import pytest

from agno.document.base import Document
from agno.document.reader.firecrawl_reader import FirecrawlReader


@pytest.fixture
def mock_scrape_response():
    """Mock response for scrape_url method"""
    return {
        "markdown": "# Test Website\n\nThis is test content from a scraped website.",
        "title": "Test Website",
        "url": "https://example.com",
    }


@pytest.fixture
def mock_crawl_response():
    """Mock response for crawl_url method"""
    return {
        "data": [
            {
                "markdown": "# Page 1\n\nThis is content from page 1.",
                "title": "Page 1",
                "url": "https://example.com/page1",
            },
            {
                "markdown": "# Page 2\n\nThis is content from page 2.",
                "title": "Page 2",
                "url": "https://example.com/page2",
            },
        ]
    }


def test_scrape_basic(mock_scrape_response):
    """Test basic scraping functionality"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = mock_scrape_response

        # Create reader and call scrape
        reader = FirecrawlReader()
        documents = reader.scrape("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].id == "https://example.com_1"
        # Content is joined with spaces instead of newlines
        expected_content = "# Test Website This is test content from a scraped website."
        assert documents[0].content == expected_content

        # Verify FirecrawlApp was called correctly
        MockFirecrawlApp.assert_called_once_with(api_key=None)
        mock_app.scrape_url.assert_called_once_with("https://example.com", params=None)


def test_scrape_with_api_key_and_params():
    """Test scraping with API key and custom parameters"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = {"markdown": "Test content"}

        # Create reader with API key and params
        api_key = "test_api_key"
        params = {"waitUntil": "networkidle2"}
        reader = FirecrawlReader(api_key=api_key, params=params)
        reader.scrape("https://example.com")

        # Verify FirecrawlApp was called with correct parameters
        MockFirecrawlApp.assert_called_once_with(api_key=api_key)
        mock_app.scrape_url.assert_called_once_with("https://example.com", params=params)


def test_scrape_empty_response():
    """Test handling of empty response from scrape_url"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock for empty response
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = {}

        # Create reader and call scrape
        reader = FirecrawlReader()
        documents = reader.scrape("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].content == ""


def test_scrape_none_content():
    """Test handling of None content from scrape_url"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock for None content
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = {"markdown": None}

        # Create reader and call scrape
        reader = FirecrawlReader()
        documents = reader.scrape("https://example.com")

        # Verify results
        assert len(documents) == 1
        assert documents[0].content == ""


def test_scrape_with_chunking(mock_scrape_response):
    """Test scraping with chunking enabled"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = mock_scrape_response

        # Create reader with chunking enabled
        reader = FirecrawlReader()
        reader.chunk = True
        reader.chunk_size = 10  # Small chunk size to ensure multiple chunks

        # Create a patch for chunk_document
        def mock_chunk_document(doc):
            # Simple mock that splits into 2 chunks
            return [
                doc,  # Original document
                Document(
                    name=doc.name,
                    # The ID already has _1 from the original document
                    id=f"{doc.id}_chunk",
                    content="Chunked content",
                ),
            ]

        with patch.object(reader, "chunk_document", side_effect=mock_chunk_document):
            # Call scrape
            documents = reader.scrape("https://example.com")

            # Verify results
            assert len(documents) == 2
            assert documents[0].name == "https://example.com"
            # Implementation doesn't add _1 before _chunk
            assert documents[1].id == "https://example.com_chunk"


def test_crawl_basic(mock_crawl_response):
    """Test basic crawling functionality"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.crawl_url.return_value = mock_crawl_response

        # Create reader and call crawl
        reader = FirecrawlReader(mode="crawl")
        documents = reader.crawl("https://example.com")

        # Verify results
        assert len(documents) == 2
        # Base URL is used for name
        assert documents[0].name == "https://example.com"
        # Content joined with spaces
        assert documents[0].content == "# Page 1 This is content from page 1."
        assert documents[1].content == "# Page 2 This is content from page 2."

        # Verify FirecrawlApp was called correctly
        MockFirecrawlApp.assert_called_once_with(api_key=None)
        mock_app.crawl_url.assert_called_once_with("https://example.com", params=None)


def test_crawl_empty_response():
    """Test handling of empty response from crawl_url"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock for empty response
        mock_app = MockFirecrawlApp.return_value
        mock_app.crawl_url.return_value = {}

        # Create reader and call crawl
        reader = FirecrawlReader(mode="crawl")
        documents = reader.crawl("https://example.com")

        # Verify results
        assert len(documents) == 0


def test_crawl_empty_data():
    """Test handling of empty data array from crawl_url"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock for empty data array
        mock_app = MockFirecrawlApp.return_value
        mock_app.crawl_url.return_value = {"data": []}

        # Create reader and call crawl
        reader = FirecrawlReader(mode="crawl")
        documents = reader.crawl("https://example.com")

        # Verify results
        assert len(documents) == 0


def test_crawl_with_chunking(mock_crawl_response):
    """Test crawling with chunking enabled"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.crawl_url.return_value = mock_crawl_response

        # Create reader with chunking enabled
        reader = FirecrawlReader(mode="crawl")
        reader.chunk = True
        reader.chunk_size = 10  # Small chunk size to ensure multiple chunks

        def mock_chunk_document(doc):
            # Simple mock that splits into 2 chunks
            return [
                doc,  # Original document
                Document(name=doc.name, id=f"{doc.id}_chunk", content="Chunked content"),
            ]

        with patch.object(reader, "chunk_document", side_effect=mock_chunk_document):
            documents = reader.crawl("https://example.com")
            assert len(documents) == 4


def test_read_scrape_mode(mock_scrape_response):
    """Test read method in scrape mode"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = mock_scrape_response

        reader = FirecrawlReader()
        documents = reader.read("https://example.com")

        assert len(documents) == 1
        expected_content = "# Test Website This is test content from a scraped website."
        assert documents[0].content == expected_content

        mock_app.scrape_url.assert_called_once()
        mock_app.crawl_url.assert_not_called()


def test_read_crawl_mode(mock_crawl_response):
    """Test read method in crawl mode"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlApp") as MockFirecrawlApp:
        # Set up mock
        mock_app = MockFirecrawlApp.return_value
        mock_app.crawl_url.return_value = mock_crawl_response

        # Create reader in crawl mode
        reader = FirecrawlReader(mode="crawl")
        documents = reader.read("https://example.com")

        assert len(documents) == 2

        mock_app.crawl_url.assert_called_once()
        mock_app.scrape_url.assert_not_called()


def test_read_invalid_mode():
    """Test read method with invalid mode"""
    reader = FirecrawlReader(mode="invalid")

    with pytest.raises(NotImplementedError):
        reader.read("https://example.com")


@pytest.mark.asyncio
async def test_async_scrape_basic(mock_scrape_response):
    """Test basic async scraping functionality"""
    with patch("asyncio.to_thread") as mock_to_thread, patch("firecrawl.FirecrawlApp") as MockFirecrawlApp:
        # Configure mock to return the expected result
        mock_app = MockFirecrawlApp.return_value
        mock_app.scrape_url.return_value = mock_scrape_response

        # Make to_thread return a document directly to avoid actual thread execution
        document = Document(
            name="https://example.com",
            id="https://example.com_1",
            content="# Test Website\n\nThis is test content from a scraped website.",
        )
        mock_to_thread.return_value = [document]

        reader = FirecrawlReader()
        documents = await reader.async_scrape("https://example.com")

        assert len(documents) == 1
        assert documents[0].name == "https://example.com"
        assert documents[0].id == "https://example.com_1"
        assert documents[0].content == "# Test Website\n\nThis is test content from a scraped website."

        # Verify to_thread was called with the right arguments
        mock_to_thread.assert_called_once()


@pytest.mark.asyncio
async def test_async_crawl_basic(mock_crawl_response):
    """Test basic async crawling functionality"""
    with patch("asyncio.to_thread") as mock_to_thread, patch("firecrawl.FirecrawlApp") as MockFirecrawlApp:
        # Configure mock for crawl
        mock_app = MockFirecrawlApp.return_value
        mock_app.crawl_url.return_value = mock_crawl_response

        # Create documents to be returned by to_thread
        documents = [
            Document(
                name="https://example.com",
                id="https://example.com_1",
                content="# Page 1\n\nThis is content from page 1.",
            ),
            Document(
                name="https://example.com",
                id="https://example.com_2",
                content="# Page 2\n\nThis is content from page 2.",
            ),
        ]
        mock_to_thread.return_value = documents

        reader = FirecrawlReader(mode="crawl")
        result = await reader.async_crawl("https://example.com")

        assert len(result) == 2
        assert result[0].name == "https://example.com"
        assert result[0].content == "# Page 1\n\nThis is content from page 1."
        assert result[1].content == "# Page 2\n\nThis is content from page 2."

        # Verify to_thread was called
        mock_to_thread.assert_called_once()


@pytest.mark.asyncio
async def test_async_read_scrape_mode(mock_scrape_response):
    """Test async_read method in scrape mode"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlReader.async_scrape") as mock_async_scrape:
        # Create a document to return
        document = Document(
            name="https://example.com",
            id="https://example.com_1",
            content="# Test Website\n\nThis is test content from a scraped website.",
        )
        mock_async_scrape.return_value = [document]

        reader = FirecrawlReader()
        documents = await reader.async_read("https://example.com")

        assert len(documents) == 1
        assert documents[0].content == "# Test Website\n\nThis is test content from a scraped website."

        # Verify async_scrape was called
        mock_async_scrape.assert_called_once_with("https://example.com")


@pytest.mark.asyncio
async def test_async_read_crawl_mode(mock_crawl_response):
    """Test async_read method in crawl mode"""
    with patch("agno.document.reader.firecrawl_reader.FirecrawlReader.async_crawl") as mock_async_crawl:
        # Create documents to return
        documents = [
            Document(
                name="https://example.com",
                id="https://example.com_1",
                content="# Page 1\n\nThis is content from page 1.",
            ),
            Document(
                name="https://example.com",
                id="https://example.com_2",
                content="# Page 2\n\nThis is content from page 2.",
            ),
        ]
        mock_async_crawl.return_value = documents

        reader = FirecrawlReader(mode="crawl")
        result = await reader.async_read("https://example.com")

        assert len(result) == 2

        # Verify async_crawl was called
        mock_async_crawl.assert_called_once_with("https://example.com")


@pytest.mark.asyncio
async def test_async_read_invalid_mode():
    """Test async_read method with invalid mode"""
    reader = FirecrawlReader(mode="invalid")

    with pytest.raises(NotImplementedError):
        await reader.async_read("https://example.com")
