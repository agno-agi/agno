import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.youcom.contents import YouContentsTools

# ── Initialization and configuration ──────────────────────────────────────────


def test_init_with_api_key():
    tools = YouContentsTools(api_key="test-key")
    assert tools.api_key == "test-key"
    assert tools.base_url == "https://ydc-index.io"


def test_init_reads_env_var(monkeypatch):
    monkeypatch.setenv("YDC_API_KEY", "env-key")
    monkeypatch.setenv("YDC_BASE_URL", "https://custom.index.io/")
    tools = YouContentsTools()
    assert tools.api_key == "env-key"
    assert tools.base_url == "https://custom.index.io"


def test_only_contents_tool_registered():
    tools = YouContentsTools()
    assert len(tools.functions) == 1
    assert "you_contents" in tools.functions


def test_default_base_url():
    tools = YouContentsTools()
    assert tools.base_url == "https://ydc-index.io"


def test_validation_crawl_timeout_invalid():
    with pytest.raises(ValueError, match="crawl_timeout must be between 1 and 60 seconds"):
        YouContentsTools(crawl_timeout=0)
    with pytest.raises(ValueError, match="crawl_timeout must be between 1 and 60 seconds"):
        YouContentsTools(crawl_timeout=61)


def test_validation_max_age_invalid():
    with pytest.raises(ValueError, match="max_age must be 0 or greater"):
        YouContentsTools(max_age=-1)


# ── Request construction ────────────────────────────────────────────────


@pytest.fixture
def mock_httpx_post():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        # Return a flat array as per API docs
        mock_response.json.return_value = [
            {
                "url": "https://example.com",
                "title": "Example",
                "html": "<p>Example</p>",
                "metadata": {"site_name": "Example Site"},
            }
        ]
        mock_post.return_value = mock_response
        yield mock_post


def test_basic_request_body_single_url(mock_httpx_post):
    tools = YouContentsTools(api_key="test")
    tools.you_contents("https://example.com")

    mock_httpx_post.assert_called_once()
    kwargs = mock_httpx_post.call_args.kwargs

    assert kwargs["headers"]["X-API-Key"] == "test"
    payload = kwargs["json"]
    assert payload["urls"] == ["https://example.com"]
    assert payload["formats"] == ["markdown", "metadata"]
    assert payload["crawl_timeout"] == 10
    assert "max_age" not in payload


def test_request_body_multiple_urls(mock_httpx_post):
    tools = YouContentsTools(api_key="test")
    urls = ["https://example.com", "https://test.com"]
    tools.you_contents(urls)

    payload = mock_httpx_post.call_args.kwargs["json"]
    assert payload["urls"] == urls


def test_parameter_overrides(mock_httpx_post):
    tools = YouContentsTools(api_key="test", crawl_timeout=10, max_age=3600)
    tools.you_contents("https://example.com", crawl_timeout=20, max_age=0)

    payload = mock_httpx_post.call_args.kwargs["json"]
    assert payload["crawl_timeout"] == 20
    assert payload["max_age"] == 0


def test_validation_overrides_invalid():
    tools = YouContentsTools(api_key="test")

    res = tools.you_contents("https://example.com", crawl_timeout=61)
    assert res.startswith("Error:")
    assert "crawl_timeout must be between 1 and 60" in res

    res = tools.you_contents("https://example.com", max_age=-5)
    assert res.startswith("Error:")
    assert "max_age must be 0 or greater" in res


# ── Response formatting ───────────────────────────────────────────────────


def test_flat_array_json_format(mock_httpx_post):
    tools = YouContentsTools(api_key="test", format="json")
    result = tools.you_contents("https://example.com")

    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert parsed[0]["title"] == "Example"


def test_flat_array_markdown_format(mock_httpx_post):
    # Setup mock to include favicon
    mock_post_instance = mock_httpx_post.return_value
    mock_post_instance.json.return_value = [
        {
            "url": "https://example.com",
            "title": "Example",
            "html": "<p>Example</p>",
            "metadata": {"site_name": "Example Site", "favicon_url": "https://favicon.com"},
        }
    ]
    tools = YouContentsTools(api_key="test", format="markdown")
    result = tools.you_contents("https://example.com")

    assert "### [Example](https://example.com)" in result
    assert "**Content (HTML)**:" in result
    assert "<p>Example</p>" in result
    assert "**Site Name**: Example Site" in result
    assert "**Favicon URL**: https://favicon.com" in result


def test_truncation():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [{"url": "https://example.com", "markdown": "A" * 6000}]
        mock_post.return_value = mock_response

        tools = YouContentsTools(api_key="test", format="markdown", text_length_limit=10)
        result = tools.you_contents("https://example.com")

        assert "A" * 10 in result
        assert "A" * 11 not in result


def test_empty_results():
    with patch("httpx.Client.post") as mock_post:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = []
        mock_post.return_value = mock_response

        tools = YouContentsTools(api_key="test")
        result = tools.you_contents("https://example.com")
        assert result == "No contents found."


def test_dynamic_client_timeout():
    """Verify that the httpx.Client timeout is dynamically set based on crawl_timeout."""
    with patch("httpx.Client") as mock_client_class:
        # Setup mock client context manager
        mock_client_instance = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client_instance

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = []
        mock_client_instance.post.return_value = mock_response

        # crawl_timeout = 20, timeout = 15 -> client timeout should be 20 + 5 = 25
        tools = YouContentsTools(api_key="test", timeout=15, crawl_timeout=20)
        tools.you_contents("https://example.com")

        # Check what arguments were passed to httpx.Client()
        mock_client_class.assert_called_with(timeout=25)

        # per-call override: crawl_timeout = 40 -> client timeout should be 40 + 5 = 45
        tools.you_contents("https://example.com", crawl_timeout=40)
        mock_client_class.assert_called_with(timeout=45)

        # per-call override: crawl_timeout = 5, default timeout = 15 -> max(15, 5+5) = 15
        tools.you_contents("https://example.com", crawl_timeout=5)
        mock_client_class.assert_called_with(timeout=15)


# ── Error handling ────────────────────────────────────────────────────────


def test_http_error_returns_message():
    with patch("httpx.Client.post") as mock_post:
        mock_error = httpx.HTTPStatusError("401 Unauthorized", request=MagicMock(), response=MagicMock())
        mock_error.response.json.return_value = {"detail": "Invalid API key"}
        mock_post.side_effect = mock_error

        tools = YouContentsTools(api_key="test")
        result = tools.you_contents("https://example.com")

        assert "Invalid API key" in result
        assert result.startswith("Error:")
