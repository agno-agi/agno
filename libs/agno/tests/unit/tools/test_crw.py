import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agno.tools.crw import CrwTools


@pytest.fixture
def crw_tools():
    """Create a CrwTools instance with all tools enabled."""
    return CrwTools(api_url="http://localhost:3000", api_key="test-key", all=True)


# --- Initialization ---


def test_init_defaults():
    tools = CrwTools()
    assert tools.api_url == "http://localhost:3000"
    assert tools.formats == ["markdown"]
    assert tools.max_content_length == 50000
    assert tools.only_main_content is True


def test_init_with_params():
    tools = CrwTools(
        api_url="http://custom:8080/",
        api_key="my-key",
        formats=["html"],
        max_content_length=1000,
        timeout=30,
    )
    assert tools.api_url == "http://custom:8080"  # trailing slash stripped
    assert tools.api_key == "my-key"
    assert tools.formats == ["html"]
    assert tools.max_content_length == 1000
    assert tools.timeout == 30


def test_init_api_key_from_env():
    with patch.dict("os.environ", {"CRW_API_KEY": "env-key"}):
        tools = CrwTools()
        assert tools.api_key == "env-key"


def test_init_tool_registration():
    tools_scrape_only = CrwTools(enable_scrape=True, enable_crawl=False)
    func_names = [fn.name for fn in tools_scrape_only.functions.values()]
    assert "scrape_url" in func_names
    assert "crawl_site" not in func_names

    tools_all = CrwTools(all=True)
    func_names_all = [fn.name for fn in tools_all.functions.values()]
    assert "scrape_url" in func_names_all
    assert "crawl_site" in func_names_all
    assert "map_site" in func_names_all
    assert "extract_data" in func_names_all


# --- _truncate_data ---


def test_truncate_data_short_string(crw_tools):
    assert crw_tools._truncate_data("short") == "short"


def test_truncate_data_long_string(crw_tools):
    crw_tools.max_content_length = 10
    result = crw_tools._truncate_data("a" * 100)
    assert result == "a" * 10 + "\n... (content truncated)"


def test_truncate_data_nested_dict(crw_tools):
    crw_tools.max_content_length = 5
    data = {"markdown": "abcdefghij", "title": "ok"}
    result = crw_tools._truncate_data(data)
    assert result["markdown"] == "abcde\n... (content truncated)"
    assert result["title"] == "ok"


def test_truncate_data_list(crw_tools):
    crw_tools.max_content_length = 3
    data = [{"text": "abcdef"}, {"text": "xy"}]
    result = crw_tools._truncate_data(data)
    assert result[0]["text"] == "abc\n... (content truncated)"
    assert result[1]["text"] == "xy"


def test_truncate_data_produces_valid_json(crw_tools):
    """Truncation must produce valid JSON when serialized."""
    crw_tools.max_content_length = 20
    data = {"markdown": "x" * 1000, "url": "https://example.com"}
    truncated = crw_tools._truncate_data(data)
    serialized = json.dumps(truncated, ensure_ascii=False)
    parsed = json.loads(serialized)
    assert isinstance(parsed, dict)
    assert "url" in parsed


# --- scrape_url ---


def _mock_response(data: dict, status_code: int = 200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status.return_value = None
    return resp


def test_scrape_url_success(crw_tools):
    mock_data = {
        "success": True,
        "data": {
            "markdown": "# Hello",
            "metadata": {"title": "Test", "statusCode": 200},
        },
    }
    with patch("agno.tools.crw.httpx.post", return_value=_mock_response(mock_data)):
        result = json.loads(crw_tools.scrape_url("https://example.com"))
        assert result["markdown"] == "# Hello"
        assert result["metadata"]["title"] == "Test"


def test_scrape_url_api_error(crw_tools):
    mock_data = {"success": False, "error": "Rate limited"}
    with patch("agno.tools.crw.httpx.post", return_value=_mock_response(mock_data)):
        result = json.loads(crw_tools.scrape_url("https://example.com"))
        assert result["error"] == "Rate limited"


def test_scrape_url_http_error(crw_tools):
    with patch("agno.tools.crw.httpx.post", side_effect=httpx.HTTPStatusError(
        "Server error", request=MagicMock(), response=MagicMock(status_code=500)
    )):
        result = json.loads(crw_tools.scrape_url("https://example.com"))
        assert "error" in result


# --- crawl_site ---


def test_crawl_site_success(crw_tools):
    start_resp = _mock_response({"success": True, "id": "job-123"})
    poll_resp = _mock_response({
        "status": "completed",
        "data": [{"markdown": "# Page 1"}],
    })
    with patch("agno.tools.crw.httpx.post", return_value=start_resp), \
         patch("agno.tools.crw.httpx.get", return_value=poll_resp), \
         patch("agno.tools.crw.time.sleep"):
        result = json.loads(crw_tools.crawl_site("https://example.com"))
        assert result[0]["markdown"] == "# Page 1"


def test_crawl_site_failed_job(crw_tools):
    start_resp = _mock_response({"success": True, "id": "job-456"})
    poll_resp = _mock_response({"status": "failed"})
    with patch("agno.tools.crw.httpx.post", return_value=start_resp), \
         patch("agno.tools.crw.httpx.get", return_value=poll_resp), \
         patch("agno.tools.crw.time.sleep"):
        result = json.loads(crw_tools.crawl_site("https://example.com"))
        assert result["error"] == "Crawl job failed"


def test_crawl_site_timeout(crw_tools):
    """Crawl polling must respect the deadline and return a timeout error."""
    crw_tools.crawl_max_pages = 1
    crw_tools.timeout = 1  # max_wait = 1 * 1 = 1 second

    start_resp = _mock_response({"success": True, "id": "job-789"})
    poll_resp = _mock_response({"status": "scraping"})

    # Simulate time passing beyond deadline
    start_time = 1000.0
    times = iter([start_time, start_time + 2.0])  # second call exceeds deadline

    with patch("agno.tools.crw.httpx.post", return_value=start_resp), \
         patch("agno.tools.crw.httpx.get", return_value=poll_resp), \
         patch("agno.tools.crw.time.sleep"), \
         patch("agno.tools.crw.time.monotonic", side_effect=times):
        result = json.loads(crw_tools.crawl_site("https://example.com"))
        assert result["status"] == "timeout"
        assert "job-789" in result["job_id"]


# --- map_site ---


def test_map_site_success(crw_tools):
    mock_data = {
        "success": True,
        "data": ["https://example.com/a", "https://example.com/b"],
    }
    with patch("agno.tools.crw.httpx.post", return_value=_mock_response(mock_data)):
        result = json.loads(crw_tools.map_site("https://example.com"))
        assert len(result) == 2


# --- extract_data ---


def test_extract_data_success(crw_tools):
    mock_data = {
        "success": True,
        "data": {"json": {"title": "Example", "price": 42}},
    }
    with patch("agno.tools.crw.httpx.post", return_value=_mock_response(mock_data)):
        schema = {"type": "object", "properties": {"title": {"type": "string"}}}
        result = json.loads(crw_tools.extract_data("https://example.com", schema))
        assert result["title"] == "Example"
        assert result["price"] == 42
