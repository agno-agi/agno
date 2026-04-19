"""Unit tests for ScrapeGraphTools class."""

import json
import os
from unittest.mock import Mock, patch

from agno.tools.scrapegraph import ScrapeGraphTools


def _make_api_result(data, status="success", error=None):
    """Helper: build a minimal stand-in for scrapegraph_py.ApiResult."""
    result = Mock()
    result.status = status
    result.data = data
    result.error = error
    result.elapsed_ms = 0
    return result


def _patch_client():
    """Patch the SDK client and return (patched_env_ctx, mock_client_class, mock_client)."""
    return patch("agno.tools.scrapegraph.ScrapeGraphAI")


def test_init_with_api_key():
    """Test initialization with API key."""
    with _patch_client() as mock_client:
        tools = ScrapeGraphTools(api_key="test_key")
        assert tools.api_key == "test_key"
        mock_client.assert_called_once_with(api_key="test_key")


def test_init_with_env_api_key():
    """Test initialization with environment API key."""
    with (
        _patch_client() as mock_client,
        patch.dict(os.environ, {"SGAI_API_KEY": "env_key"}),
    ):
        tools = ScrapeGraphTools()
        assert tools.api_key == "env_key"
        mock_client.assert_called_once_with(api_key="env_key")


def test_scrape_basic_functionality():
    """Test basic scrape functionality."""
    with (
        _patch_client() as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = json.dumps({"results": {"html": {"data": "<html>test</html>"}}})
        mock_client.scrape.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert "<html>test</html>" in result
        mock_client.scrape.assert_called_once()
        call_args = mock_client.scrape.call_args[0][0]
        assert str(call_args.url).rstrip("/") == "https://example.com"
        assert call_args.fetch_config is None
        assert call_args.formats[0].type == "html"


def test_scrape_with_render_heavy_js():
    """Test scrape with render_heavy_js enabled."""
    with (
        _patch_client() as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = "{}"
        mock_client.scrape.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True, render_heavy_js=True)
        tools.scrape("https://spa-site.com")

        call_args = mock_client.scrape.call_args[0][0]
        assert call_args.fetch_config is not None
        assert call_args.fetch_config.mode == "js"


def test_scrape_error_handling():
    """Test scrape error handling via ApiResult error status."""
    with (
        _patch_client() as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = _make_api_result(data=None, status="error", error="API Error")

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert result.startswith("Error:")
        assert "API Error" in result


def test_smartscraper_basic():
    """Test smartscraper basic functionality (now backed by SDK extract)."""
    with (
        _patch_client() as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.json_data = {"title": "example"}
        data.raw = None
        mock_client.extract.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_smartscraper=True)
        result = tools.smartscraper("https://example.com", "extract title")

        assert json.loads(result) == {"title": "example"}
        mock_client.extract.assert_called_once()
        call_args = mock_client.extract.call_args[0][0]
        assert call_args.prompt == "extract title"
        assert str(call_args.url).rstrip("/") == "https://example.com"


def test_markdownify_basic():
    """Test markdownify basic functionality (now backed by SDK scrape+markdown)."""
    with (
        _patch_client() as mock_client_class,
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.results = {"markdown": {"data": "# Title\n\nContent"}}
        mock_client.scrape.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        assert result == "# Title\n\nContent"
        mock_client.scrape.assert_called_once()
        call_args = mock_client.scrape.call_args[0][0]
        assert call_args.formats[0].type == "markdown"


def test_tool_selection():
    """Test that only selected tools are enabled."""
    with (
        _patch_client(),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
    ):
        tools = ScrapeGraphTools(enable_scrape=True, enable_smartscraper=True, enable_markdownify=False)

        tool_names = [func.__name__ for func in tools.tools]
        assert "scrape" in tool_names
        assert "smartscraper" in tool_names
