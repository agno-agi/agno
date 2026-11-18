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


def _job_api(*poll_responses, job_id="job_1"):
    """Fake httpx.request: the POST submits a pending job, each GET returns the next poll response."""
    polls = list(poll_responses)

    def fake_request(method, url, **kwargs):
        if method == "POST":
            return _mock_response({"jobId": job_id, "status": "pending"})
        return _mock_response(polls.pop(0) if len(polls) > 1 else polls[0])

    return fake_request


@pytest.fixture
def anakin_tools():
    """Create an AnakinTools instance with every tool enabled."""
    with patch.dict("os.environ", {"ANAKIN_API_KEY": TEST_API_KEY}):
        return AnakinTools(all=True, poll_interval=0, max_wait_time=5)


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("agno.tools.anakin.time.sleep"):
        yield


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
    tools = AnakinTools(
        api_key="param_api_key",
        country="de",
        api_base_url="https://custom.anakin.io/v1",
        timeout=30,
        poll_interval=1,
        max_wait_time=10,
    )
    assert tools.api_key == "param_api_key"
    assert tools.country == "de"
    assert tools.api_base_url == "https://custom.anakin.io/v1"
    assert tools.timeout == 30
    assert tools.poll_interval == 1
    assert tools.max_wait_time == 10


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
    completed = {"id": "job_1", "status": "completed", "markdown": "# Example Domain"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        result = anakin_tools.scrape_url("https://example.com")

    assert "Example Domain" in result
    submit, poll = mock_request.call_args_list
    assert submit.args == ("POST", "https://api.anakin.io/v1/url-scraper")
    assert submit.kwargs["json"]["url"] == "https://example.com"
    assert submit.kwargs["json"]["country"] == "us"
    assert submit.kwargs["headers"]["Authorization"] == f"Bearer {TEST_API_KEY}"
    assert poll.args == ("GET", "https://api.anakin.io/v1/url-scraper/job_1")


def test_scrape_url_polls_until_completed(anakin_tools):
    api = _job_api(
        {"id": "job_1", "status": "pending"},
        {"id": "job_1", "status": "processing"},
        {"id": "job_1", "status": "completed", "markdown": "done"},
    )
    with patch("agno.tools.anakin.httpx.request", side_effect=api) as mock_request:
        result = anakin_tools.scrape_url("https://example.com")

    assert "done" in result
    assert mock_request.call_count == 4  # 1 submit + 3 polls


def test_scrape_url_forwards_options(anakin_tools):
    completed = {"id": "job_1", "status": "completed", "markdown": "content"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        anakin_tools.scrape_url("https://example.com", generate_json=True, use_browser=True, country="de")

    payload = mock_request.call_args_list[0].kwargs["json"]
    assert payload["generateJson"] is True
    assert payload["useBrowser"] is True
    assert payload["country"] == "de"


def test_scrape_url_job_failed(anakin_tools):
    failed = {"id": "job_1", "status": "failed", "error": "Connection timeout"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(failed)):
        result = anakin_tools.scrape_url("https://example.com")

    assert result.startswith("Error scraping https://example.com")
    assert "Connection timeout" in result


def test_scrape_url_timeout(anakin_tools):
    anakin_tools.max_wait_time = 0
    pending = {"id": "job_1", "status": "processing"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(pending)):
        result = anakin_tools.scrape_url("https://example.com")

    assert result.startswith("Error scraping https://example.com")
    assert "job_1" in result
    assert "still 'processing'" in result


def test_scrape_url_submit_missing_job_id(anakin_tools):
    with patch("agno.tools.anakin.httpx.request", return_value=_mock_response({"status": "pending"})):
        result = anakin_tools.scrape_url("https://example.com")

    assert "did not return a job id" in result


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
    completed = {
        "id": "job_1",
        "status": "completed",
        "totalPages": 2,
        "completedPages": 2,
        "results": [{"url": "https://example.com", "status": "completed", "markdown": "# Home"}],
    }
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        result = anakin_tools.crawl_website("https://example.com", max_pages=2)

    assert "# Home" in result  # page content, not just the job id
    submit, poll = mock_request.call_args_list
    assert submit.args == ("POST", "https://api.anakin.io/v1/crawl")
    assert submit.kwargs["json"]["url"] == "https://example.com"
    assert submit.kwargs["json"]["maxPages"] == 2
    assert submit.kwargs["json"]["depth"] == 1
    assert poll.args == ("GET", "https://api.anakin.io/v1/crawl/job_1")


def test_crawl_website_polls_until_completed(anakin_tools):
    api = _job_api(
        {"id": "job_1", "status": "pending"},
        {"id": "job_1", "status": "processing"},
        {"id": "job_1", "status": "completed", "results": [{"url": "https://example.com", "markdown": "ok"}]},
    )
    with patch("agno.tools.anakin.httpx.request", side_effect=api):
        result = anakin_tools.crawl_website("https://example.com")

    assert '"status": "completed"' in result
    assert "jobId" not in result


def test_crawl_website_job_failed(anakin_tools):
    failed = {"id": "job_1", "status": "failed", "error": "Blocked by robots"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(failed)):
        result = anakin_tools.crawl_website("https://example.com")

    assert result.startswith("Error crawling https://example.com")
    assert "Blocked by robots" in result


def test_crawl_website_timeout(anakin_tools):
    anakin_tools.max_wait_time = 0
    pending = {"id": "job_1", "status": "pending"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(pending)):
        result = anakin_tools.crawl_website("https://example.com")

    assert result.startswith("Error crawling https://example.com")
    assert "job_1" in result


def test_crawl_website_forwards_patterns(anakin_tools):
    completed = {"id": "job_1", "status": "completed", "totalPages": 0}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        anakin_tools.crawl_website(
            "https://example.com",
            include_patterns=["/blog/*"],
            exclude_patterns=["/admin/*"],
        )

    payload = mock_request.call_args_list[0].kwargs["json"]
    assert payload["includePatterns"] == ["/blog/*"]
    assert payload["excludePatterns"] == ["/admin/*"]


def test_crawl_website_omits_unset_patterns(anakin_tools):
    completed = {"id": "job_1", "status": "completed", "totalPages": 0}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        anakin_tools.crawl_website("https://example.com")

    payload = mock_request.call_args_list[0].kwargs["json"]
    assert "includePatterns" not in payload
    assert "excludePatterns" not in payload


# ============================================================================
# MAP TESTS
# ============================================================================


def test_map_website(anakin_tools):
    completed = {"id": "job_1", "status": "completed", "links": ["https://example.com/a"], "totalLinks": 1}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        result = anakin_tools.map_website("https://example.com")

    assert "https://example.com/a" in result  # discovered links, not just the job id
    submit, poll = mock_request.call_args_list
    assert submit.args == ("POST", "https://api.anakin.io/v1/map")
    assert submit.kwargs["json"]["url"] == "https://example.com"
    assert submit.kwargs["json"]["limit"] == 100
    assert submit.kwargs["json"]["depth"] == 2
    assert poll.args == ("GET", "https://api.anakin.io/v1/map/job_1")


def test_map_website_polls_until_completed(anakin_tools):
    api = _job_api(
        {"id": "job_1", "status": "pending"},
        {"id": "job_1", "status": "completed", "links": ["https://example.com/a"], "totalLinks": 1},
    )
    with patch("agno.tools.anakin.httpx.request", side_effect=api):
        result = anakin_tools.map_website("https://example.com")

    assert "totalLinks" in result
    assert "jobId" not in result


def test_map_website_job_failed(anakin_tools):
    failed = {"id": "job_1", "status": "failed", "error": "Unreachable"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(failed)):
        result = anakin_tools.map_website("https://example.com")

    assert result.startswith("Error mapping https://example.com")
    assert "Unreachable" in result


def test_map_website_timeout(anakin_tools):
    anakin_tools.max_wait_time = 0
    pending = {"id": "job_1", "status": "processing"}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(pending)):
        result = anakin_tools.map_website("https://example.com")

    assert result.startswith("Error mapping https://example.com")
    assert "job_1" in result


def test_map_website_forwards_options(anakin_tools):
    completed = {"id": "job_1", "status": "completed", "totalLinks": 0}
    with patch("agno.tools.anakin.httpx.request", side_effect=_job_api(completed)) as mock_request:
        anakin_tools.map_website(
            "https://example.com",
            include_external_links=True,
            include_subdomains=True,
            search="pricing",
        )

    payload = mock_request.call_args_list[0].kwargs["json"]
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
