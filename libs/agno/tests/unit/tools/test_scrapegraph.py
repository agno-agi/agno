"""Unit tests for ScrapeGraphTools class."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.tools.scrapegraph import ScrapeGraphTools


@pytest.fixture
def mock_scrapegraph_client():
    """Create a mock ScrapeGraph client."""
    mock_client = Mock()

    # Simple mock responses
    mock_client.scrape.return_value = {
        "html": "<html><body>Test content</body></html>",
        "request_id": "req_123",
    }

    mock_client.smartscraper.return_value = {
        "result": "extracted data",
        "request_id": "req_123",
    }

    mock_client.markdownify.return_value = {
        "result": "# Test Page\n\nTest content",
    }

    mock_client.searchscraper.return_value = {"result": [{"title": "Test Result", "url": "https://example.com"}]}

    mock_client.crawl.return_value = {"result": [{"page": "https://example.com", "data": {"title": "Test"}}]}

    mock_client.agenticscraper.return_value = {
        "result": {"content": "scraped content"},
        "request_id": "req_123",
    }

    return mock_client


@pytest.fixture
def scrapegraph_tools():
    """Create ScrapeGraphTools instance with mocked client."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock responses
        mock_client.scrape.return_value = {"html": "test html", "request_id": "123"}
        mock_client.smartscraper.return_value = {"result": "test data", "request_id": "123"}

        tools = ScrapeGraphTools(enable_scrape=True)
        return tools


def test_init_with_api_key():
    """Test initialization with API key."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client,
        patch("agno.tools.scrapegraph.sgai_logger"),
    ):
        tools = ScrapeGraphTools(api_key="test_key")
        assert tools.api_key == "test_key"
        mock_client.assert_called_once_with(api_key="test_key")


def test_init_with_env_api_key():
    """Test initialization with environment API key."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "env_key"}),
    ):
        tools = ScrapeGraphTools()
        assert tools.api_key == "env_key"
        mock_client.assert_called_once_with(api_key="env_key")


def test_scrape_basic_functionality():
    """Test basic scrape functionality."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = {
            "html": "<html>test</html>",
            "request_id": "req_123",
        }

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        result_data = json.loads(result)
        assert result_data["html"] == "<html>test</html>"
        assert result_data["request_id"] == "req_123"

        mock_client.scrape.assert_called_once_with(
            website_url="https://example.com",
            headers=None,
            render_heavy_js=False,
        )


def test_scrape_with_render_heavy_js():
    """Test scrape with render_heavy_js enabled."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = {"html": "js content", "request_id": "123"}

        tools = ScrapeGraphTools(enable_scrape=True, render_heavy_js=True)
        tools.scrape("https://spa-site.com")

        mock_client.scrape.assert_called_once_with(
            website_url="https://spa-site.com",
            headers=None,
            render_heavy_js=True,
        )


def test_scrape_error_handling():
    """Test scrape error handling."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.side_effect = Exception("API Error")

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert result.startswith("Error:")
        assert "API Error" in result


def test_smartscraper_basic():
    """Test smartscraper basic functionality."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.smartscraper.return_value = {"result": "extracted data"}

        tools = ScrapeGraphTools(enable_smartscraper=True)
        result = tools.smartscraper("https://example.com", "extract title")

        result_data = json.loads(result)
        assert result_data == "extracted data"

        mock_client.smartscraper.assert_called_once_with(website_url="https://example.com", user_prompt="extract title")


def test_markdownify_basic():
    """Test markdownify basic functionality."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.markdownify.return_value = {"result": "# Title\n\nContent"}

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        assert result == "# Title\n\nContent"
        mock_client.markdownify.assert_called_once_with(website_url="https://example.com")


def test_tool_selection():
    """Test that only selected tools are enabled."""
    with (
        patch("agno.tools.scrapegraph.Client"),
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        # Test specific tool selection
        tools = ScrapeGraphTools(enable_scrape=True, enable_smartscraper=True, enable_markdownify=False)

        tool_names = [func.__name__ for func in tools.tools]
        assert "scrape" in tool_names
        assert "smartscraper" in tool_names
        # When smartscraper=False, markdownify is auto-enabled, so we test with both enabled
