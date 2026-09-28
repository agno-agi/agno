"""Unit tests for AnakinTools class."""

import os
from unittest.mock import Mock, patch

import httpx
import pytest

from agno.tools.anakin import AnakinTools

TEST_API_KEY = os.environ.get("ANAKIN_API_KEY", "test_api_key")


def _mock_response(payload):
    response = Mock(spec=httpx.Response)
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


@pytest.fixture
def anakin_tools():
    """Create an AnakinTools instance with every tool enabled."""
    with patch.dict("os.environ", {"ANAKIN_API_KEY": TEST_API_KEY}):
        return AnakinTools(all=True)


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_env_var():
    with patch.dict("os.environ", {"ANAKIN_API_KEY": TEST_API_KEY}, clear=True):
        tools = AnakinTools()
        assert tools.api_key == TEST_API_KEY
        assert tools.country == "us"
        assert tools.api_base_url == "https://api.anakin.io/v1"


def test_init_with_params():
    tools = AnakinTools(api_key="param_api_key", country="de", api_base_url="https://custom.anakin.io/v1", timeout=30)
    assert tools.api_key == "param_api_key"
    assert tools.country == "de"
    assert tools.api_base_url == "https://custom.anakin.io/v1"
    assert tools.timeout == 30


def test_init_default_tools():
    tools = AnakinTools(api_key=TEST_API_KEY)
    tool_names = [tool.__name__ for tool in tools.tools]
    assert tool_names == ["scrape_url"]


def test_init_with_all_flag():
    tools = AnakinTools(api_key=TEST_API_KEY, all=True)
    tool_names = {tool.__name__ for tool in tools.tools}
    assert tool_names == {"scrape_url", "crawl_website", "map_website", "search_web"}


def test_init_missing_api_key_logs_error():
    with patch.dict("os.environ", {}, clear=True):
        with patch("agno.tools.anakin.log_error") as mock_log_error:
            tools = AnakinTools()
            assert tools.api_key is None
            mock_log_error.assert_called_once()


# ============================================================================
# SCRAPE TESTS
# ============================================================================


def test_scrape_url(anakin_tools):
    mock_response = _mock_response({"url": "https://example.com", "markdown": "# Example Domain", "cached": False})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        result = anakin_tools.scrape_url("https://example.com")

    assert "Example Domain" in result
    args, kwargs = mock_request.call_args
    assert args == ("POST", "https://api.anakin.io/v1/scrape")
    assert kwargs["json"]["url"] == "https://example.com"
    assert kwargs["json"]["country"] == "us"
    assert kwargs["headers"]["Authorization"] == f"Bearer {TEST_API_KEY}"


def test_scrape_url_forwards_options(anakin_tools):
    mock_response = _mock_response({"url": "https://example.com", "markdown": "content"})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        anakin_tools.scrape_url(
            "https://example.com", generate_json=True, use_browser=True, force_fresh=True, country="de"
        )

    payload = mock_request.call_args[1]["json"]
    assert payload["generateJson"] is True
    assert payload["useBrowser"] is True
    assert payload["forceFresh"] is True
    assert payload["country"] == "de"


def test_scrape_url_missing_api_key():
    with patch.dict("os.environ", {}, clear=True):
        tools = AnakinTools()

    result = tools.scrape_url("https://example.com")
    assert "Error" in result
    assert "ANAKIN_API_KEY" in result


def test_scrape_url_http_error(anakin_tools):
    error_response = Mock(spec=httpx.Response)
    error_response.status_code = 401
    error_response.text = "Unauthorized"
    with patch(
        "agno.tools.anakin.httpx.request",
        side_effect=httpx.HTTPStatusError("Unauthorized", request=Mock(), response=error_response),
    ):
        result = anakin_tools.scrape_url("https://example.com")

    assert "Error" in result
    assert "401" in result


def test_scrape_url_request_exception(anakin_tools):
    with patch("agno.tools.anakin.httpx.request", side_effect=httpx.ConnectError("boom")):
        result = anakin_tools.scrape_url("https://example.com")

    assert "Error" in result
    assert "boom" in result


# ============================================================================
# CRAWL TESTS
# ============================================================================


def test_crawl_website(anakin_tools):
    mock_response = _mock_response({"url": "https://example.com", "totalPages": 2, "completedPages": 2})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        result = anakin_tools.crawl_website("https://example.com", max_pages=2)

    assert "completedPages" in result
    payload = mock_request.call_args[1]["json"]
    assert payload["url"] == "https://example.com"
    assert payload["maxPages"] == 2
    assert payload["depth"] == 1


def test_crawl_website_forwards_patterns(anakin_tools):
    mock_response = _mock_response({"totalPages": 0})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        anakin_tools.crawl_website(
            "https://example.com",
            include_patterns=["/blog/*"],
            exclude_patterns=["/admin/*"],
        )

    payload = mock_request.call_args[1]["json"]
    assert payload["includePatterns"] == ["/blog/*"]
    assert payload["excludePatterns"] == ["/admin/*"]


def test_crawl_website_omits_unset_patterns(anakin_tools):
    mock_response = _mock_response({"totalPages": 0})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        anakin_tools.crawl_website("https://example.com")

    payload = mock_request.call_args[1]["json"]
    assert "includePatterns" not in payload
    assert "excludePatterns" not in payload


# ============================================================================
# MAP TESTS
# ============================================================================


def test_map_website(anakin_tools):
    mock_response = _mock_response({"url": "https://example.com", "links": ["https://example.com/a"], "totalLinks": 1})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        result = anakin_tools.map_website("https://example.com")

    assert "totalLinks" in result
    payload = mock_request.call_args[1]["json"]
    assert payload["url"] == "https://example.com"
    assert payload["limit"] == 100
    assert payload["depth"] == 2


def test_map_website_forwards_options(anakin_tools):
    mock_response = _mock_response({"totalLinks": 0})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        anakin_tools.map_website(
            "https://example.com",
            include_external_links=True,
            include_subdomains=True,
            search="pricing",
        )

    payload = mock_request.call_args[1]["json"]
    assert payload["includeExternalLinks"] is True
    assert payload["includeSubdomains"] is True
    assert payload["search"] == "pricing"


# ============================================================================
# SEARCH TESTS
# ============================================================================


def test_search_web(anakin_tools):
    mock_response = _mock_response(
        {"results": [{"url": "https://example.com", "title": "Example", "snippet": "..."}], "count": 1}
    )
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        result = anakin_tools.search_web("agno ai agent framework")

    assert "Example" in result
    payload = mock_request.call_args[1]["json"]
    assert payload["prompt"] == "agno ai agent framework"
    assert payload["limit"] == 5


def test_search_web_custom_limit(anakin_tools):
    mock_response = _mock_response({"results": [], "count": 0})
    with patch("agno.tools.anakin.httpx.request", return_value=mock_response) as mock_request:
        anakin_tools.search_web("query", limit=3)

    payload = mock_request.call_args[1]["json"]
    assert payload["limit"] == 3
