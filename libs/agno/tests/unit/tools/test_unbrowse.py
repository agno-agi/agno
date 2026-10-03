import json
from unittest.mock import Mock, patch

import httpx
import pytest

from agno.tools.unbrowse import UnbrowseTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure UNBROWSE_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("UNBROWSE_API_KEY", raising=False)


@pytest.fixture
def tools():
    return UnbrowseTools(api_key="test_key", all=True)


def _rpc_result(payload, is_error=False):
    """A successful JSON-RPC envelope whose text content is the JSON-encoded payload."""
    mock = Mock(spec=httpx.Response)
    mock.raise_for_status.return_value = None
    mock.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": is_error},
    }
    return mock


def _rpc_error(message):
    mock = Mock(spec=httpx.Response)
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": message}}
    return mock


def _sent(mock_post):
    """The JSON-RPC params of the last request."""
    return mock_post.call_args.kwargs["json"]["params"]


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_without_api_key():
    tools = UnbrowseTools()
    assert tools.api_key is None


def test_init_with_env_var(monkeypatch):
    monkeypatch.setenv("UNBROWSE_API_KEY", "env_key")
    assert UnbrowseTools().api_key == "env_key"


def test_init_constructor_key_overrides_env(monkeypatch):
    monkeypatch.setenv("UNBROWSE_API_KEY", "env_key")
    assert UnbrowseTools(api_key="direct_key").api_key == "direct_key"


def test_init_defaults():
    tools = UnbrowseTools(api_key="k")
    assert tools.base_url == "https://unbrowse.ai/api/mcp"
    assert tools.timeout == 120.0
    assert tools.render is None


def test_default_tools_registered():
    tools = UnbrowseTools(api_key="k")
    assert list(tools.functions.keys()) == ["scrape_page", "discover", "run_task"]


def test_all_tools_registered():
    tools = UnbrowseTools(api_key="k", all=True)
    assert list(tools.functions.keys()) == ["scrape_page", "discover", "run_task", "map_site"]


def test_flags_disable_tools():
    tools = UnbrowseTools(
        api_key="k", enable_scrape_page=False, enable_discover=False, enable_run_task=False, enable_map_site=True
    )
    assert list(tools.functions.keys()) == ["map_site"]


# ---------------------------------------------------------------------------
# Request shape
# ---------------------------------------------------------------------------


def test_request_is_jsonrpc_tools_call(tools):
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result({"ok": True})) as mock_post:
        tools.discover("search hacker news")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://unbrowse.ai/api/mcp"
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"
    assert kwargs["headers"]["Content-Type"] == "application/json"
    assert kwargs["headers"]["Accept"] == "application/json"
    assert kwargs["timeout"] == 120.0
    body = kwargs["json"]
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "tools/call"
    assert body["params"] == {"name": "unbrowse.discover", "arguments": {"query": "search hacker news"}}


def test_custom_base_url_and_timeout():
    tools = UnbrowseTools(api_key="k", base_url="https://example.test/mcp", timeout=5)
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result({})) as mock_post:
        tools.scrape_page("https://example.com")
    assert mock_post.call_args.args[0] == "https://example.test/mcp"
    assert mock_post.call_args.kwargs["timeout"] == 5


# ---------------------------------------------------------------------------
# scrape_page
# ---------------------------------------------------------------------------


def test_scrape_page_success(tools):
    page = {
        "url": "https://example.com",
        "metadata": {"title": "Example Domain", "statusCode": 200},
        "markdown": "# Example Domain",
    }
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result(page)) as mock_post:
        result = json.loads(tools.scrape_page("https://example.com"))

    assert result["markdown"] == "# Example Domain"
    assert result["metadata"]["title"] == "Example Domain"
    assert _sent(mock_post) == {
        "name": "unbrowse.scrape",
        "arguments": {"url": "https://example.com", "formats": ["markdown"]},
    }


def test_scrape_page_passes_render():
    tools = UnbrowseTools(api_key="k", render="never")
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result({})) as mock_post:
        tools.scrape_page("https://example.com")
    assert _sent(mock_post)["arguments"]["render"] == "never"


def test_scrape_page_empty_url(tools):
    with patch("agno.tools.unbrowse.httpx.post") as mock_post:
        result = json.loads(tools.scrape_page(""))
    assert "error" in result
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# discover
# ---------------------------------------------------------------------------


def test_discover_success(tools):
    found = {"private": [{"kind": "capability", "id": "learned.hn_algolia_com.get_search", "title": "search HN"}]}
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result(found)):
        result = json.loads(tools.discover("search hacker news"))
    assert result["private"][0]["id"] == "learned.hn_algolia_com.get_search"


def test_discover_empty_query(tools):
    with patch("agno.tools.unbrowse.httpx.post") as mock_post:
        result = json.loads(tools.discover(""))
    assert "error" in result
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# run_task
# ---------------------------------------------------------------------------


def test_run_task_by_task(tools):
    run = {"runId": "run_1", "status": "succeeded", "result": {"items": [1, 2]}}
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result(run)) as mock_post:
        result = json.loads(tools.run_task(task="top stories on Hacker News"))
    assert result["status"] == "succeeded"
    assert _sent(mock_post) == {"name": "unbrowse.run", "arguments": {"task": "top stories on Hacker News"}}


def test_run_task_by_capability_with_input(tools):
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result({"status": "succeeded"})) as mock_post:
        tools.run_task(task="ignored", capability="learned.x.get_search", input={"query": "agno"})
    assert _sent(mock_post)["arguments"] == {"capability": "learned.x.get_search", "input": {"query": "agno"}}


def test_run_task_input_required_passed_through(tools):
    run = {"status": "input_required", "requirements": [{"name": "date", "type": "string"}]}
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result(run)):
        result = json.loads(tools.run_task(capability="learned.x.book"))
    assert result["status"] == "input_required"
    assert result["requirements"][0]["name"] == "date"


def test_run_task_no_capability_passed_through(tools):
    run = {"status": "failed", "phase": "no_capability", "error": {"code": "no_capability", "message": "none"}}
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result(run, is_error=True)):
        result = json.loads(tools.run_task(task="something nothing can do"))
    assert result["phase"] == "no_capability"


def test_run_task_requires_task_or_capability(tools):
    with patch("agno.tools.unbrowse.httpx.post") as mock_post:
        result = json.loads(tools.run_task())
    assert "error" in result
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# map_site
# ---------------------------------------------------------------------------


def test_map_site_success(tools):
    site = {"url": "https://docs.agno.com", "count": 1, "urls": ["https://docs.agno.com/"]}
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_result(site)) as mock_post:
        result = json.loads(tools.map_site("https://docs.agno.com"))
    assert result["urls"] == ["https://docs.agno.com/"]
    assert _sent(mock_post) == {"name": "unbrowse.map", "arguments": {"url": "https://docs.agno.com"}}


def test_map_site_empty_url(tools):
    with patch("agno.tools.unbrowse.httpx.post") as mock_post:
        result = json.loads(tools.map_site(""))
    assert "error" in result
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_missing_api_key_skips_request():
    tools = UnbrowseTools(all=True)
    with patch("agno.tools.unbrowse.httpx.post") as mock_post:
        result = json.loads(tools.scrape_page("https://example.com"))
    assert "UNBROWSE_API_KEY" in result["error"]
    mock_post.assert_not_called()


def test_jsonrpc_error(tools):
    with patch("agno.tools.unbrowse.httpx.post", return_value=_rpc_error("Unknown tool unbrowse.x")):
        result = json.loads(tools.discover("anything"))
    assert result == {"error": "Unknown tool unbrowse.x"}


def test_http_status_error(tools):
    request = httpx.Request("POST", "https://unbrowse.ai/api/mcp")
    response = httpx.Response(401, request=request, text='{"error":"invalid_token"}')
    mock = Mock(spec=httpx.Response)
    mock.raise_for_status.side_effect = httpx.HTTPStatusError("401", request=request, response=response)
    with patch("agno.tools.unbrowse.httpx.post", return_value=mock):
        result = json.loads(tools.discover("anything"))
    assert "401" in result["error"]
    assert "invalid_token" in result["error"]


def test_network_error(tools):
    with patch("agno.tools.unbrowse.httpx.post", side_effect=httpx.ConnectError("connection refused")):
        result = json.loads(tools.scrape_page("https://example.com"))
    assert "connection refused" in result["error"]


def test_invalid_json(tools):
    mock = Mock(spec=httpx.Response)
    mock.raise_for_status.return_value = None
    mock.json.side_effect = ValueError("bad json")
    with patch("agno.tools.unbrowse.httpx.post", return_value=mock):
        result = json.loads(tools.scrape_page("https://example.com"))
    assert "Invalid JSON" in result["error"]


def test_empty_content(tools):
    mock = Mock(spec=httpx.Response)
    mock.raise_for_status.return_value = None
    mock.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
    with patch("agno.tools.unbrowse.httpx.post", return_value=mock):
        result = json.loads(tools.scrape_page("https://example.com"))
    assert "error" in result
