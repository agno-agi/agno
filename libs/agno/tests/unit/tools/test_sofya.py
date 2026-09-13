import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.sofya import SofyaTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure SOFYA_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("SOFYA_API_KEY", raising=False)
    monkeypatch.delenv("SOFYA_BASE_URL", raising=False)


@pytest.fixture
def api_tools():
    """SofyaTools with a known API key and all tools enabled for testing."""
    return SofyaTools(api_key="test_key", all=True, format="json")


def _mock_response(payload: dict) -> Mock:
    mock = Mock(spec=requests.Response)
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


# Initialization Tests
def test_init_without_api_key_and_env(monkeypatch):
    """If no api_key argument and no SOFYA_API_KEY in env, api_key should be None."""
    monkeypatch.delenv("SOFYA_API_KEY", raising=False)
    tools = SofyaTools()
    assert tools.api_key is None


def test_init_with_env_var(monkeypatch):
    """If SOFYA_API_KEY is set in the environment, it is picked up."""
    monkeypatch.setenv("SOFYA_API_KEY", "env_key")
    tools = SofyaTools(api_key=None)
    assert tools.api_key == "env_key"


def test_init_base_url_default():
    """Base URL defaults to https://sofya.co."""
    tools = SofyaTools(api_key="test_key")
    assert tools.base_url == "https://sofya.co"


def test_init_base_url_override(monkeypatch):
    """SOFYA_BASE_URL env var overrides the default and trailing slashes are stripped."""
    monkeypatch.setenv("SOFYA_BASE_URL", "https://eu.sofya.co/")
    tools = SofyaTools(api_key="test_key")
    assert tools.base_url == "https://eu.sofya.co"


def test_enabled_tools_registration():
    """Only enabled tools are registered on the toolkit."""
    search_only = SofyaTools(api_key="test_key")
    names = {f.name for f in search_only.functions.values()}
    assert "search_web" in names
    assert "extract_url_content" not in names

    all_tools = SofyaTools(api_key="test_key", all=True)
    all_names = {f.name for f in all_tools.functions.values()}
    assert {"search_web", "extract_url_content", "research"}.issubset(all_names)


# Search Tests
def test_search_no_api_key():
    """Calling search without any API key returns an error message."""
    tools = SofyaTools(api_key=None)
    result = json.loads(tools.search_web("anything"))
    assert "error" in result
    assert "Sofya API key" in result["error"]


def test_search_empty_query(api_tools):
    """Calling search with an empty query returns an error message."""
    result = json.loads(api_tools.search_web(""))
    assert "error" in result
    assert "query" in result["error"].lower()


def test_search_success_json(api_tools):
    """A successful search returns cleaned results as JSON."""
    payload = {
        "query": "mcp",
        "answer": "Model Context Protocol.",
        "results": [
            {"title": "MCP", "url": "https://example.com", "content": "about mcp", "published_date": "2026-01-01"}
        ],
        "credits_used": 3,
    }
    with patch("agno.tools.sofya.requests.post", return_value=_mock_response(payload)) as mock_post:
        result = json.loads(api_tools.search_web("mcp"))
    mock_post.assert_called_once()
    assert result["answer"] == "Model Context Protocol."
    assert result["results"][0]["url"] == "https://example.com"
    # internal fields are not leaked into the cleaned result
    assert "credits_used" not in result


def test_search_markdown_format():
    """Markdown format renders a heading and result links."""
    tools = SofyaTools(api_key="test_key", format="markdown")
    payload = {
        "query": "mcp",
        "answer": "A protocol.",
        "results": [{"title": "MCP", "url": "https://e.com", "content": "x"}],
    }
    with patch("agno.tools.sofya.requests.post", return_value=_mock_response(payload)):
        result = tools.search_web("mcp")
    assert "# mcp" in result
    assert "### Summary" in result
    assert "[MCP](https://e.com)" in result


def test_search_request_error(api_tools):
    """Network errors are caught and returned as an error message."""
    with patch("agno.tools.sofya.requests.post", side_effect=requests.ConnectionError("boom")):
        result = json.loads(api_tools.search_web("mcp"))
    assert "error" in result
    assert "boom" in result["error"]


# Extract Tests
def test_extract_no_urls(api_tools):
    """Extract with no valid URLs returns an error."""
    result = json.loads(api_tools.extract_url_content("   "))
    assert "error" in result


def test_extract_success(api_tools):
    """Extract returns markdown sections per URL."""
    payload = {"results": [{"url": "https://example.com", "content": "# Hello", "success": True}]}
    with patch("agno.tools.sofya.requests.post", return_value=_mock_response(payload)):
        result = api_tools.extract_url_content("https://example.com")
    assert "## https://example.com" in result
    assert "# Hello" in result


def test_extract_failed_result(api_tools):
    """A failed fetch result is reported clearly."""
    payload = {"results": [{"url": "https://bad.com", "success": False, "error": "timeout"}]}
    with patch("agno.tools.sofya.requests.post", return_value=_mock_response(payload)):
        result = api_tools.extract_url_content("https://bad.com")
    assert "Extraction failed" in result
    assert "timeout" in result


# Research Tests
def test_research_no_api_key():
    """Research without an API key returns an error."""
    tools = SofyaTools(api_key=None, enable_research=True)
    result = json.loads(tools.research("anything"))
    assert "error" in result


def test_research_success_markdown():
    """Research renders the report and a sources list in markdown."""
    tools = SofyaTools(api_key="test_key", enable_research=True, format="markdown")
    payload = {
        "query": "what is mcp",
        "report": "MCP is a protocol.",
        "sources": [{"title": "Spec", "url": "https://spec.example"}],
    }
    with patch("agno.tools.sofya.requests.post", return_value=_mock_response(payload)):
        result = tools.research("what is mcp")
    assert "MCP is a protocol." in result
    assert "## Sources" in result
    assert "[Spec](https://spec.example)" in result


# Tests for markdown fallbacks and API limits.
def test_search_markdown_handles_missing_title_and_content():
    """Sofya may omit title/content for some results; markdown must not render the literal 'None'."""
    tools = SofyaTools(api_key="test_key", format="markdown")
    payload = {
        "query": "q",
        "results": [
            {"url": "https://e.com"},  # no title, no content
            {"title": None, "url": "https://f.com", "content": None},
        ],
    }
    with patch("agno.tools.sofya.requests.post", return_value=_mock_response(payload)):
        result = tools.search_web("q")
    assert "None" not in result
    # Falls back to the URL as the link text when title is missing.
    assert "[https://e.com](https://e.com)" in result
    assert "[https://f.com](https://f.com)" in result


def test_extract_url_content_caps_at_ten_urls(api_tools):
    """Sofya's fetch endpoint caps at 10 URLs — the tool must trim client-side."""
    urls = ",".join(f"https://e{i}.com" for i in range(15))
    with patch(
        "agno.tools.sofya.requests.post",
        return_value=_mock_response({"results": []}),
    ) as mock_post:
        api_tools.extract_url_content(urls)
    sent = mock_post.call_args.kwargs["json"]["urls"]
    assert len(sent) == 10
    assert sent[0] == "https://e0.com"
    assert sent[-1] == "https://e9.com"


def test_post_surfaces_http_error_body(api_tools):
    """HTTP errors should include Sofya's response body, not just the status line."""
    mock_resp = Mock(spec=requests.Response)
    mock_resp.text = '{"error":"insufficient credits"}'
    mock_resp.raise_for_status.side_effect = requests.HTTPError(
        "402 Client Error: Payment Required for url: https://sofya.co/v1/search",
        response=mock_resp,
    )
    with patch("agno.tools.sofya.requests.post", return_value=mock_resp):
        result = json.loads(api_tools.search_web("q"))
    assert "error" in result
    assert "insufficient credits" in result["error"]
    assert "402" in result["error"]
