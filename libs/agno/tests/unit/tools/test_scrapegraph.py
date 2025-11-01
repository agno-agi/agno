"""Unit tests for ScrapeGraphTools class."""

import json
import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from agno.tools.scrapegraph import ScrapeGraphTools


@pytest.fixture
def mock_httpx_response():
    """Create mock httpx responses."""
    
    def create_response(json_data, status_code=200):
        mock_response = Mock()
        mock_response.json.return_value = json_data
        mock_response.status_code = status_code
        mock_response.raise_for_status.return_value = None
        return mock_response
    
    return create_response


@pytest.fixture
def scrapegraph_tools():
    """Create ScrapeGraphTools instance with mocked HTTP client."""
    with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
        tools = ScrapeGraphTools(enable_scrape=True)
        return tools


def test_init_with_api_key():
    """Test initialization with API key."""
    tools = ScrapeGraphTools(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.headers["SGAI-APIKEY"] == "test_key"


def test_init_with_env_api_key():
    """Test initialization with environment API key."""
    with patch.dict(os.environ, {"SGAI_API_KEY": "env_key"}):
        tools = ScrapeGraphTools()
        assert tools.api_key == "env_key"
        assert tools.headers["SGAI-APIKEY"] == "env_key"


def test_init_without_api_key():
    """Test initialization fails without API key."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="API key is required"):
            ScrapeGraphTools()


def test_scrape_basic_functionality():
    """Test basic scrape functionality."""
    with (
        patch("agno.tools.scrapegraph.httpx.Client") as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "html": "<html>test</html>",
            "scrape_request_id": "req_123",
            "status": "completed"
        }
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_class.return_value = mock_client

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        result_data = json.loads(result)
        assert result_data["html"] == "<html>test</html>"
        assert result_data["scrape_request_id"] == "req_123"


def test_scrape_with_render_heavy_js():
    """Test scrape with render_heavy_js enabled."""
    with (
        patch("agno.tools.scrapegraph.httpx.Client") as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.json.return_value = {"html": "js content", "scrape_request_id": "123"}
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_class.return_value = mock_client

        tools = ScrapeGraphTools(enable_scrape=True, render_heavy_js=True)
        result = tools.scrape("https://spa-site.com")

        # Verify the call was made with render_heavy_js=True in payload
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["render_heavy_js"] is True


def test_scrape_error_handling():
    """Test scrape error handling."""
    with (
        patch("agno.tools.scrapegraph.httpx.Client") as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = MagicMock()
        mock_client.post.side_effect = Exception("API Error")
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_class.return_value = mock_client

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert result.startswith("Error:")
        assert "API Error" in result


def test_smartscraper_basic():
    """Test smartscraper basic functionality."""
    with (
        patch("agno.tools.scrapegraph.httpx.Client") as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.json.return_value = {"result": "extracted data", "status": "completed"}
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_class.return_value = mock_client

        tools = ScrapeGraphTools(enable_smartscraper=True)
        result = tools.smartscraper("https://example.com", "extract title")

        result_data = json.loads(result)
        assert result_data == "extracted data"


def test_markdownify_basic():
    """Test markdownify basic functionality."""
    with (
        patch("agno.tools.scrapegraph.httpx.Client") as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = MagicMock()
        mock_response = Mock()
        mock_response.json.return_value = {"result": "# Title\n\nContent", "status": "completed"}
        mock_response.raise_for_status.return_value = None
        mock_client.post.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client_class.return_value = mock_client

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        assert result == "# Title\n\nContent"


def test_tool_selection():
    """Test that only selected tools are enabled."""
    with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
        # Test specific tool selection
        tools = ScrapeGraphTools(enable_scrape=True, enable_smartscraper=True, enable_markdownify=False)

        tool_names = [func.__name__ for func in tools.tools]
        assert "scrape" in tool_names
        assert "smartscraper" in tool_names
        # When smartscraper=False, markdownify is auto-enabled, so we test with both enabled
