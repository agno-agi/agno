"""Unit tests for ScrapeGraphTools."""

import json
import os
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("scrapegraph_py")

from agno.tools.scrapegraph import ScrapeGraphTools  # noqa: E402


def _api_result(data, status="success", error=None):
    result = Mock()
    result.status = status
    result.data = data
    result.error = error
    result.elapsed_ms = 0
    return result


def _patch_client():
    return patch("agno.tools.scrapegraph.ScrapeGraphAI")


def test_init_with_api_key():
    with _patch_client() as mock_client:
        tools = ScrapeGraphTools(api_key="test_key")
        assert tools.api_key == "test_key"
        mock_client.assert_called_once_with(api_key="test_key")


def test_init_with_env_api_key():
    with _patch_client() as mock_client, patch.dict(os.environ, {"SGAI_API_KEY": "env_key"}):
        tools = ScrapeGraphTools()
        assert tools.api_key == "env_key"
        mock_client.assert_called_once_with(api_key="env_key")


def test_init_default_registers_only_smartscraper():
    with _patch_client():
        tools = ScrapeGraphTools()
        names = [t.__name__ for t in tools.tools]
        assert names == ["smartscraper"]


def test_init_all_flag_registers_every_tool():
    with _patch_client():
        tools = ScrapeGraphTools(all=True)
        names = {t.__name__ for t in tools.tools}
        assert names == {"smartscraper", "markdownify", "searchscraper", "crawl", "scrape"}


def test_init_selective_flags():
    with _patch_client():
        tools = ScrapeGraphTools(enable_smartscraper=False, enable_scrape=True)
        names = [t.__name__ for t in tools.tools]
        assert names == ["scrape"]


def test_smartscraper_basic():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.json_data = {"title": "example"}
        data.raw = None
        mock_client.extract.return_value = _api_result(data)

        tools = ScrapeGraphTools(enable_smartscraper=True)
        result = tools.smartscraper("https://example.com", "extract title")

        assert json.loads(result) == {"title": "example"}
        _, kwargs = mock_client.extract.call_args
        assert kwargs["prompt"] == "extract title"
        assert kwargs["url"] == "https://example.com"


def test_smartscraper_error_returns_error_string():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.extract.return_value = _api_result(data=None, status="error", error="API down")

        tools = ScrapeGraphTools(enable_smartscraper=True)
        result = tools.smartscraper("https://example.com", "prompt")

        assert result.startswith("Error")
        assert "API down" in result


def test_markdownify_basic():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = json.dumps({"results": {"markdown": {"data": "# Title"}}})
        mock_client.scrape.return_value = _api_result(data)

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        assert "# Title" in result
        args, kwargs = mock_client.scrape.call_args
        assert args[0] == "https://example.com"
        assert kwargs["formats"][0].type == "markdown"


def test_markdownify_error_returns_error_string():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = _api_result(data=None, status="error", error="rate limited")

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        assert result.startswith("Error")
        assert "rate limited" in result


def test_scrape_basic():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = json.dumps({"results": {"html": {"data": "<html>x</html>"}}})
        mock_client.scrape.return_value = _api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert "<html>x</html>" in result
        args, kwargs = mock_client.scrape.call_args
        assert args[0] == "https://example.com"
        assert kwargs["formats"][0].type == "html"
        assert kwargs["fetch_config"] is None


def test_scrape_with_render_heavy_js():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = "{}"
        mock_client.scrape.return_value = _api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True, render_heavy_js=True)
        tools.scrape("https://spa-site.com")

        _, kwargs = mock_client.scrape.call_args
        assert kwargs["fetch_config"].mode == "js"


def test_scrape_with_custom_headers():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = "{}"
        mock_client.scrape.return_value = _api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True)
        tools.scrape("https://example.com", headers={"X-Custom": "abc"})

        _, kwargs = mock_client.scrape.call_args
        assert kwargs["fetch_config"].headers == {"X-Custom": "abc"}


def test_scrape_error_returns_error_string():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = _api_result(data=None, status="error", error="bad url")

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert result.startswith("Error")
        assert "bad url" in result


def test_searchscraper_basic():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = json.dumps({"results": [{"title": "t"}]})
        mock_client.search.return_value = _api_result(data)

        tools = ScrapeGraphTools(enable_searchscraper=True)
        result = tools.searchscraper("what is X")

        assert json.loads(result) == {"results": [{"title": "t"}]}
        mock_client.search.assert_called_once_with("what is X")


def test_searchscraper_error_returns_error_string():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = _api_result(data=None, status="error", error="quota exceeded")

        tools = ScrapeGraphTools(enable_searchscraper=True)
        result = tools.searchscraper("q")

        assert result.startswith("Error")
        assert "quota exceeded" in result


def _crawl_resource(start_result, *get_results):
    resource = Mock()
    resource.start.return_value = start_result
    resource.get.side_effect = list(get_results)
    return resource


def test_crawl_completes_without_polling():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        finished = Mock()
        finished.id = "c1"
        finished.status = "completed"
        finished.model_dump_json.return_value = json.dumps({"pages": [{"url": "https://x.com"}]})
        mock_client.crawl = _crawl_resource(_api_result(finished))

        tools = ScrapeGraphTools(enable_crawl=True)
        with patch("agno.tools.scrapegraph.time.sleep") as no_sleep:
            result = tools.crawl("https://x.com", prompt="extract", schema={"type": "object"})

        assert not mock_client.crawl.get.called
        assert not no_sleep.called
        assert json.loads(result)["pages"][0]["url"] == "https://x.com"


def test_crawl_polls_until_complete():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        running = Mock()
        running.id = "c2"
        running.status = "running"
        done = Mock()
        done.id = "c2"
        done.status = "completed"
        done.model_dump_json.return_value = json.dumps({"status": "completed"})

        mock_client.crawl = _crawl_resource(
            _api_result(running),
            _api_result(running),
            _api_result(done),
        )

        tools = ScrapeGraphTools(enable_crawl=True)
        with (
            patch("agno.tools.scrapegraph._CRAWL_POLL_INTERVAL", 2),
            patch("agno.tools.scrapegraph.time.sleep") as slept,
        ):
            result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        assert mock_client.crawl.get.call_count == 2
        assert slept.call_count == 2
        for call in slept.call_args_list:
            assert call.args[0] == 2
        assert json.loads(result)["status"] == "completed"


def test_crawl_times_out():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        running = Mock()
        running.id = "c3"
        running.status = "running"
        mock_client.crawl = Mock()
        mock_client.crawl.start.return_value = _api_result(running)
        mock_client.crawl.get.return_value = _api_result(running)

        # Fake time progression: first call at 0, next past deadline.
        times = iter([0.0, 1000.0])
        with (
            patch("agno.tools.scrapegraph.time.monotonic", side_effect=lambda: next(times)),
            patch("agno.tools.scrapegraph.time.sleep"),
            patch("agno.tools.scrapegraph._CRAWL_MAX_WAIT", 60),
        ):
            tools = ScrapeGraphTools(enable_crawl=True)
            result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        assert result.startswith("Error")
        assert "timed out" in result
        assert "c3" in result


def test_crawl_start_error_returns_error_string():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.crawl = Mock()
        mock_client.crawl.start.return_value = _api_result(data=None, status="error", error="bad schema")

        tools = ScrapeGraphTools(enable_crawl=True)
        result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        assert result.startswith("Error")
        assert "bad schema" in result
