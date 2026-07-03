"""Unit tests for YouTools class."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.youcom import YouTools


@pytest.fixture
def youcom_tools():
    """Create a YouTools instance with a fake API key."""
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        return YouTools()


def _mock_response(payload):
    response = MagicMock(spec=httpx.Response)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _patch_client(payload):
    """Patch ``httpx.Client`` so any GET returns the given JSON payload."""
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = _mock_response(payload)
    return patch("agno.tools.youcom.httpx.Client", return_value=client), client


def test_init_with_api_key():
    """API key passed via constructor is preferred over the env var."""
    tools = YouTools(api_key="explicit-key")
    assert tools.api_key == "explicit-key"


def test_init_reads_env_var():
    """API key is read from YDC_API_KEY when not provided."""
    with patch.dict("os.environ", {"YDC_API_KEY": "env-key"}):
        tools = YouTools()
        assert tools.api_key == "env-key"


def test_only_search_tool_registered():
    """YouTools should expose exactly one tool: you_search."""
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        tools = YouTools()
        names = [func.name for func in tools.functions.values()]
        assert names == ["you_search"]


def test_base_url_strips_trailing_slash():
    tools = YouTools(api_key="k", base_url="https://custom.example.com/")
    assert tools.base_url == "https://custom.example.com"


def test_search_success(youcom_tools):
    payload = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Test Article",
                "description": "A short snippet",
                "markdown": "Sample text content",
                "published_date": "2024-01-01",
            }
        ]
    }
    patcher, client = _patch_client(payload)
    with patcher:
        result = youcom_tools.you_search("test query", num_results=3)
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["url"] == "https://example.com"
    assert parsed[0]["title"] == "Test Article"
    assert parsed[0]["snippet"] == "A short snippet"
    assert parsed[0]["text"] == "Sample text content"
    assert parsed[0]["published_date"] == "2024-01-01"

    args, kwargs = client.get.call_args
    assert args[0].endswith("/v1/search")
    assert kwargs["params"]["query"] == "test query"
    assert kwargs["params"]["count"] == 3
    assert kwargs["params"]["livecrawl"] == "web"
    assert kwargs["params"]["livecrawl_formats"] == "markdown"
    assert kwargs["headers"]["X-API-Key"] == "test-key"


def test_search_passes_domain_filters():
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        tools = YouTools(
            include_domains=["example.com", "example.org"],
            exclude_domains=["spam.com"],
        )

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("filtered query")

    params = client.get.call_args.kwargs["params"]
    assert params["include_domains"] == "example.com,example.org"
    assert params["exclude_domains"] == "spam.com"


def test_search_markdown_format():
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        tools = YouTools(format="markdown")

    payload = {
        "results": [
            {
                "url": "https://example.com",
                "title": "Hello",
                "description": "world",
                "markdown": "body",
            }
        ]
    }
    patcher, _ = _patch_client(payload)
    with patcher:
        result = tools.you_search("hi")

    assert "# Results for: hi" in result
    assert "[Hello](https://example.com)" in result
    assert "world" in result
    assert "body" in result


def test_search_text_truncation():
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        tools = YouTools(text_length_limit=10)

    long_text = "x" * 200
    patcher, _ = _patch_client({"results": [{"url": "https://example.com", "markdown": long_text}]})
    with patcher:
        result = tools.you_search("query")

    parsed = json.loads(result)
    assert parsed[0]["text"] == "x" * 10


def test_search_falls_back_to_default_count():
    with patch.dict("os.environ", {"YDC_API_KEY": "test-key"}):
        tools = YouTools(num_results=8)

    patcher, client = _patch_client({"results": []})
    with patcher:
        tools.you_search("query")

    assert client.get.call_args.kwargs["params"]["count"] == 8


def test_search_http_error_returns_message(youcom_tools):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = httpx.ConnectError("boom")
    with patch("agno.tools.youcom.httpx.Client", return_value=client):
        result = youcom_tools.you_search("query")
    assert result.startswith("Error:")
