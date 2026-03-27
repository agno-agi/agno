import json
import os
from unittest.mock import Mock, patch

import pytest
from firecrawl import FirecrawlApp  # noqa

from agno.tools.firecrawl import FirecrawlTools

TEST_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "test_api_key")
TEST_API_URL = "https://api.firecrawl.dev"


@pytest.fixture
def mock_firecrawl():
    """Create a mock FirecrawlApp instance."""
    with patch("agno.tools.firecrawl.FirecrawlApp") as mock_firecrawl_cls:
        mock_app = Mock()
        mock_firecrawl_cls.return_value = mock_app
        return mock_app


@pytest.fixture
def firecrawl_tools(mock_firecrawl):
    """Create a FirecrawlTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"FIRECRAWL_API_KEY": TEST_API_KEY}):
        tools = FirecrawlTools()
        # Directly set the app to our mock to avoid initialization issues
        tools.app = mock_firecrawl
        return tools


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.firecrawl.FirecrawlApp"):
        with patch.dict("os.environ", {"FIRECRAWL_API_KEY": TEST_API_KEY}, clear=True):
            tools = FirecrawlTools()
            assert tools.api_key == TEST_API_KEY
            assert tools.formats is None
            assert tools.limit == 10
            assert tools.app is not None


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.firecrawl.FirecrawlApp"):
        tools = FirecrawlTools(api_key="param_api_key", formats=["html", "text"], limit=5, api_url=TEST_API_URL)
        assert tools.api_key == "param_api_key"
        assert tools.formats == ["html", "text"]
        assert tools.limit == 5
        assert tools.app is not None


def test_scrape_website(firecrawl_tools, mock_firecrawl):
    """Test scrape_website method."""
    # Setup mock response
    mock_response = Mock()
    mock_response.model_dump.return_value = {
        "url": "https://example.com",
        "content": "Test content",
        "status": "success",
    }
    mock_firecrawl.scrape.return_value = mock_response

    # Call the method
    result = firecrawl_tools.scrape_website("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["url"] == "https://example.com"
    assert result_data["content"] == "Test content"
    assert result_data["status"] == "success"
    mock_firecrawl.scrape.assert_called_once_with("https://example.com")


def test_scrape_website_with_formats(firecrawl_tools, mock_firecrawl):
    """Test scrape_website method with formats."""
    # Setup mock response
    mock_response = Mock()
    mock_response.model_dump.return_value = {
        "url": "https://example.com",
        "content": "Test content",
        "status": "success",
    }
    mock_firecrawl.scrape.return_value = mock_response

    # Set formats
    firecrawl_tools.formats = ["html", "text"]

    # Call the method
    result = firecrawl_tools.scrape_website("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["url"] == "https://example.com"
    assert result_data["content"] == "Test content"
    assert result_data["status"] == "success"
    mock_firecrawl.scrape.assert_called_once_with("https://example.com", formats=["html", "text"])


def test_crawl_website(firecrawl_tools, mock_firecrawl):
    """Test crawl_website method."""
    # Setup mock response
    mock_response = Mock()
    mock_response.model_dump.return_value = {
        "url": "https://example.com",
        "pages": ["page1", "page2"],
        "status": "success",
    }
    mock_firecrawl.crawl.return_value = mock_response

    # Call the method
    result = firecrawl_tools.crawl_website("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["url"] == "https://example.com"
    assert result_data["pages"] == ["page1", "page2"]
    assert result_data["status"] == "success"
    mock_firecrawl.crawl.assert_called_once_with("https://example.com", limit=10, poll_interval=30)


def test_crawl_website_with_custom_limit(firecrawl_tools, mock_firecrawl):
    """Test crawl_website method with custom limit."""
    # Reset the default limit
    firecrawl_tools.limit = None
    # Setup mock response
    mock_response = Mock()
    mock_response.model_dump.return_value = {
        "url": "https://example.com",
        "pages": ["page1", "page2"],
        "status": "success",
    }
    mock_firecrawl.crawl.return_value = mock_response

    # Call the method with custom limit
    result = firecrawl_tools.crawl_website("https://example.com", limit=5)
    result_data = json.loads(result)

    # Verify results
    assert result_data["url"] == "https://example.com"
    assert result_data["pages"] == ["page1", "page2"]
    assert result_data["status"] == "success"
    mock_firecrawl.crawl.assert_called_once_with("https://example.com", limit=5, poll_interval=30)


def test_map_website(firecrawl_tools, mock_firecrawl):
    """Test map_website method."""
    # Setup mock response
    mock_response = Mock()
    mock_response.model_dump.return_value = {
        "url": "https://example.com",
        "sitemap": {"page1": ["link1", "link2"]},
        "status": "success",
    }
    mock_firecrawl.map.return_value = mock_response

    # Call the method
    result = firecrawl_tools.map_website("https://example.com")
    result_data = json.loads(result)

    # Verify results
    assert result_data["url"] == "https://example.com"
    assert result_data["sitemap"] == {"page1": ["link1", "link2"]}
    assert result_data["status"] == "success"
    mock_firecrawl.map.assert_called_once_with("https://example.com")


def test_search(firecrawl_tools, mock_firecrawl):
    """Test search method."""
    # Setup mock response
    mock_response = Mock()
    mock_response.success = True
    mock_response.data = {"query": "test query", "results": ["result1", "result2"], "status": "success"}
    mock_firecrawl.search.return_value = mock_response

    # Call the method
    result = firecrawl_tools.search_web("test query")
    result_data = json.loads(result)

    # Verify results
    assert result_data["query"] == "test query"
    assert result_data["results"] == ["result1", "result2"]
    assert result_data["status"] == "success"
    mock_firecrawl.search.assert_called_once_with("test query", limit=10)


def test_search_with_error(firecrawl_tools, mock_firecrawl):
    """Test search method with error response."""
    # Setup mock response
    mock_response = Mock()
    mock_response.success = False
    mock_response.error = "Search failed"
    mock_firecrawl.search.return_value = mock_response

    # Call the method
    result = firecrawl_tools.search_web("test query")

    # Verify results
    assert result == "Error searching with the Firecrawl tool: Search failed"
    mock_firecrawl.search.assert_called_once_with("test query", limit=10)


def test_search_with_custom_params(firecrawl_tools, mock_firecrawl):
    """Test search method with custom search parameters."""
    # Setup mock response
    mock_response = Mock()
    mock_response.success = True
    mock_response.data = {"query": "test query", "results": ["result1", "result2"], "status": "success"}
    mock_firecrawl.search.return_value = mock_response

    # Set custom search parameters
    firecrawl_tools.search_params = {"language": "en", "region": "us"}

    # Call the method
    result = firecrawl_tools.search_web("test query")
    result_data = json.loads(result)

    # Verify results
    assert result_data["query"] == "test query"
    assert result_data["results"] == ["result1", "result2"]
    assert result_data["status"] == "success"
    mock_firecrawl.search.assert_called_once_with("test query", limit=10, language="en", region="us")


def test_search_tool_response(firecrawl_tools, mock_firecrawl):
    mock_response = Mock(spec=["model_dump"])
    mock_response.model_dump.return_value = {
        "query": "test query",
        "results": ["result1", "result2"],
    }
    mock_firecrawl.search.return_value = mock_response

    result = firecrawl_tools.search_web("test query")
    result_data = json.loads(result)

    assert result_data["query"] == "test query"
    assert result_data["results"] == ["result1", "result2"]
    mock_firecrawl.search.assert_called_once_with("test query", limit=10)
