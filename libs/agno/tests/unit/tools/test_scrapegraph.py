import json
import os
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("scrapegraph_py")

from agno.tools.scrapegraph import ScrapeGraphTools  # noqa: E402

TEST_API_KEY = os.environ.get("SGAI_API_KEY", "test_api_key")


@pytest.fixture
def mock_scrapegraph():
    """Create a mock ScrapeGraphAI client."""
    with patch("agno.tools.scrapegraph.ScrapeGraphAI") as mock_client_cls:
        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def scrapegraph_tools(mock_scrapegraph):
    """Create a ScrapeGraphTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"SGAI_API_KEY": TEST_API_KEY}):
        tools = ScrapeGraphTools(all=True)
        tools.client = mock_scrapegraph
        return tools


def _api_result(data, status="success", error=None):
    """Build a minimal stand-in for scrapegraph_py.ApiResult."""
    result = Mock()
    result.status = status
    result.data = data
    result.error = error
    result.elapsed_ms = 0
    return result


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.scrapegraph.ScrapeGraphAI"):
        with patch.dict("os.environ", {"SGAI_API_KEY": TEST_API_KEY}, clear=True):
            tools = ScrapeGraphTools()
            assert tools.api_key == TEST_API_KEY
            assert tools.render_heavy_js is False
            assert tools.crawl_poll_interval == 3
            assert tools.crawl_max_wait == 180


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.scrapegraph.ScrapeGraphAI"):
        tools = ScrapeGraphTools(
            api_key="param_api_key",
            render_heavy_js=True,
            crawl_poll_interval=5,
            crawl_max_wait=600,
        )
        assert tools.api_key == "param_api_key"
        assert tools.render_heavy_js is True
        assert tools.crawl_poll_interval == 5
        assert tools.crawl_max_wait == 600


def test_init_default_registers_only_smartscraper():
    """Test that smartscraper is the only tool enabled by default."""
    with patch("agno.tools.scrapegraph.ScrapeGraphAI"):
        tools = ScrapeGraphTools()
        names = [t.__name__ for t in tools.tools]
        assert names == ["smartscraper"]


def test_init_all_flag_registers_every_tool():
    """Test that `all=True` enables every tool."""
    with patch("agno.tools.scrapegraph.ScrapeGraphAI"):
        tools = ScrapeGraphTools(all=True)
        names = {t.__name__ for t in tools.tools}
        assert names == {"smartscraper", "markdownify", "searchscraper", "crawl", "scrape"}


def test_init_selective_flags():
    """Test that selective enable flags register only the requested tools."""
    with patch("agno.tools.scrapegraph.ScrapeGraphAI"):
        tools = ScrapeGraphTools(enable_smartscraper=False, enable_scrape=True)
        names = [t.__name__ for t in tools.tools]
        assert names == ["scrape"]


def test_smartscraper(scrapegraph_tools, mock_scrapegraph):
    """Test smartscraper method."""
    data = Mock()
    data.json_data = {"title": "example"}
    data.raw = None
    mock_scrapegraph.extract.return_value = _api_result(data)

    result = scrapegraph_tools.smartscraper("https://example.com", "extract title")
    result_data = json.loads(result)

    assert result_data == {"title": "example"}
    _, kwargs = mock_scrapegraph.extract.call_args
    assert kwargs["prompt"] == "extract title"
    assert kwargs["url"] == "https://example.com"


def test_smartscraper_error(scrapegraph_tools, mock_scrapegraph):
    """Test smartscraper returns an error string when the API fails."""
    mock_scrapegraph.extract.return_value = _api_result(data=None, status="error", error="API down")

    result = scrapegraph_tools.smartscraper("https://example.com", "prompt")

    assert result.startswith("Error")
    assert "API down" in result


def test_markdownify(scrapegraph_tools, mock_scrapegraph):
    """Test markdownify method returns plain markdown text."""
    data = Mock()
    data.results = {"markdown": {"data": "# Title\n\nContent"}}
    mock_scrapegraph.scrape.return_value = _api_result(data)

    result = scrapegraph_tools.markdownify("https://example.com")

    assert result == "# Title\n\nContent"
    args, kwargs = mock_scrapegraph.scrape.call_args
    assert args[0] == "https://example.com"
    assert kwargs["formats"][0].type == "markdown"


def test_markdownify_error(scrapegraph_tools, mock_scrapegraph):
    """Test markdownify returns an error string when the API fails."""
    mock_scrapegraph.scrape.return_value = _api_result(data=None, status="error", error="rate limited")

    result = scrapegraph_tools.markdownify("https://example.com")

    assert result.startswith("Error")
    assert "rate limited" in result


def test_scrape(scrapegraph_tools, mock_scrapegraph):
    """Test scrape method returns raw HTML."""
    data = Mock()
    data.model_dump_json.return_value = json.dumps({"results": {"html": {"data": "<html>x</html>"}}})
    mock_scrapegraph.scrape.return_value = _api_result(data)

    result = scrapegraph_tools.scrape("https://example.com")

    assert "<html>x</html>" in result
    args, kwargs = mock_scrapegraph.scrape.call_args
    assert args[0] == "https://example.com"
    assert kwargs["formats"][0].type == "html"
    assert kwargs["fetch_config"] is None


def test_scrape_with_render_heavy_js(mock_scrapegraph):
    """Test scrape with JavaScript rendering enabled."""
    with patch.dict("os.environ", {"SGAI_API_KEY": TEST_API_KEY}):
        tools = ScrapeGraphTools(enable_scrape=True, render_heavy_js=True)
        tools.client = mock_scrapegraph

        data = Mock()
        data.model_dump_json.return_value = "{}"
        mock_scrapegraph.scrape.return_value = _api_result(data)

        tools.scrape("https://spa-site.com")

        _, kwargs = mock_scrapegraph.scrape.call_args
        assert kwargs["fetch_config"].mode == "js"


def test_toolkit_level_headers_applied_to_every_call(mock_scrapegraph):
    """Test that constructor-level `headers` flow into the SDK FetchConfig."""
    with patch.dict("os.environ", {"SGAI_API_KEY": TEST_API_KEY}):
        tools = ScrapeGraphTools(all=True, headers={"User-Agent": "custom-ua"})
        tools.client = mock_scrapegraph

        # smartscraper
        extract_data = Mock()
        extract_data.json_data = {"ok": True}
        extract_data.raw = None
        mock_scrapegraph.extract.return_value = _api_result(extract_data)
        tools.smartscraper("https://x.com", "extract")
        _, extract_kwargs = mock_scrapegraph.extract.call_args
        assert extract_kwargs["fetch_config"].headers == {"User-Agent": "custom-ua"}

        # scrape
        scrape_data = Mock()
        scrape_data.model_dump_json.return_value = "{}"
        mock_scrapegraph.scrape.return_value = _api_result(scrape_data)
        tools.scrape("https://x.com")
        _, scrape_kwargs = mock_scrapegraph.scrape.call_args
        assert scrape_kwargs["fetch_config"].headers == {"User-Agent": "custom-ua"}


def test_scrape_error(scrapegraph_tools, mock_scrapegraph):
    """Test scrape returns an error string when the API fails."""
    mock_scrapegraph.scrape.return_value = _api_result(data=None, status="error", error="bad url")

    result = scrapegraph_tools.scrape("https://example.com")

    assert result.startswith("Error")
    assert "bad url" in result


def test_searchscraper(scrapegraph_tools, mock_scrapegraph):
    """Test searchscraper method."""
    data = Mock()
    data.model_dump_json.return_value = json.dumps({"results": [{"title": "t"}]})
    mock_scrapegraph.search.return_value = _api_result(data)

    result = scrapegraph_tools.searchscraper("what is X")
    result_data = json.loads(result)

    assert result_data == {"results": [{"title": "t"}]}
    args, kwargs = mock_scrapegraph.search.call_args
    assert args[0] == "what is X"
    assert kwargs["fetch_config"] is None


def test_searchscraper_error(scrapegraph_tools, mock_scrapegraph):
    """Test searchscraper returns an error string when the API fails."""
    mock_scrapegraph.search.return_value = _api_result(data=None, status="error", error="quota exceeded")

    result = scrapegraph_tools.searchscraper("q")

    assert result.startswith("Error")
    assert "quota exceeded" in result


def test_crawl_completes_without_polling(scrapegraph_tools, mock_scrapegraph):
    """Test crawl returns immediately when the job is already completed."""
    finished = Mock()
    finished.id = "c1"
    finished.status = "completed"
    finished.model_dump_json.return_value = json.dumps({"pages": [{"url": "https://x.com"}]})
    mock_scrapegraph.crawl = Mock()
    mock_scrapegraph.crawl.start.return_value = _api_result(finished)

    with patch("agno.tools.scrapegraph.time.sleep") as no_sleep:
        result = scrapegraph_tools.crawl("https://x.com", prompt="extract", schema={"type": "object"})

    assert not mock_scrapegraph.crawl.get.called
    assert not no_sleep.called
    assert json.loads(result)["pages"][0]["url"] == "https://x.com"


def test_crawl_polls_until_complete(mock_scrapegraph):
    """Test crawl polls until the job completes."""
    with patch.dict("os.environ", {"SGAI_API_KEY": TEST_API_KEY}):
        tools = ScrapeGraphTools(enable_crawl=True, crawl_poll_interval=2)
        tools.client = mock_scrapegraph

        running = Mock()
        running.id = "c2"
        running.status = "running"
        done = Mock()
        done.id = "c2"
        done.status = "completed"
        done.model_dump_json.return_value = json.dumps({"status": "completed"})

        mock_scrapegraph.crawl = Mock()
        mock_scrapegraph.crawl.start.return_value = _api_result(running)
        mock_scrapegraph.crawl.get.side_effect = [_api_result(running), _api_result(done)]

        with patch("agno.tools.scrapegraph.time.sleep") as slept:
            result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        assert mock_scrapegraph.crawl.get.call_count == 2
        assert slept.call_count == 2
        for call in slept.call_args_list:
            assert call.args[0] == 2
        assert json.loads(result)["status"] == "completed"


def test_crawl_times_out(mock_scrapegraph):
    """Test crawl returns a timeout error when the deadline is exceeded."""
    with patch.dict("os.environ", {"SGAI_API_KEY": TEST_API_KEY}):
        tools = ScrapeGraphTools(enable_crawl=True, crawl_max_wait=60)
        tools.client = mock_scrapegraph

        running = Mock()
        running.id = "c3"
        running.status = "running"
        mock_scrapegraph.crawl = Mock()
        mock_scrapegraph.crawl.start.return_value = _api_result(running)
        mock_scrapegraph.crawl.get.return_value = _api_result(running)

        # Fake monotonic so the deadline is exceeded after the first poll.
        times = iter([0.0, 1000.0])
        with (
            patch("agno.tools.scrapegraph.time.monotonic", side_effect=lambda: next(times)),
            patch("agno.tools.scrapegraph.time.sleep"),
        ):
            result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        assert result.startswith("Error")
        assert "timed out" in result
        assert "c3" in result


def test_crawl_start_error(scrapegraph_tools, mock_scrapegraph):
    """Test crawl returns an error string when the start request fails."""
    mock_scrapegraph.crawl = Mock()
    mock_scrapegraph.crawl.start.return_value = _api_result(data=None, status="error", error="bad schema")

    result = scrapegraph_tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

    assert result.startswith("Error")
    assert "bad schema" in result
