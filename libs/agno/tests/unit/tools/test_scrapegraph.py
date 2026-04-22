"""Unit tests for ScrapeGraphTools class."""

import json
import os
import warnings
from unittest.mock import Mock, patch

import pytest

# Skip the whole module when the optional SDK isn't installed so pytest
# collection doesn't crash in environments that don't pull the extras.
pytest.importorskip("scrapegraph_py")

from agno.tools.scrapegraph import (  # noqa: E402
    _CRAWL_MAX_WAIT_SECONDS,
    _CRAWL_POLL_INTERVAL_SECONDS,
    ScrapeGraphTools,
)


def _make_api_result(data, status="success", error=None):
    """Build a minimal stand-in for scrapegraph_py.ApiResult."""
    result = Mock()
    result.status = status
    result.data = data
    result.error = error
    result.elapsed_ms = 0
    return result


def _patch_client():
    """Patch the SDK client at the toolkit's import site."""
    return patch("agno.tools.scrapegraph.ScrapeGraphAI")


# ---- Initialization --------------------------------------------------------


def test_init_with_api_key():
    with _patch_client() as mock_client:
        tools = ScrapeGraphTools(api_key="test_key")
        assert tools.api_key == "test_key"
        mock_client.assert_called_once_with(api_key="test_key")


def test_init_with_env_api_key():
    with (
        _patch_client() as mock_client,
        patch.dict(os.environ, {"SGAI_API_KEY": "env_key"}),
    ):
        tools = ScrapeGraphTools()
        assert tools.api_key == "env_key"
        mock_client.assert_called_once_with(api_key="env_key")


def test_init_explicit_api_key_overrides_env():
    with (
        _patch_client() as mock_client,
        patch.dict(os.environ, {"SGAI_API_KEY": "env_key"}),
    ):
        tools = ScrapeGraphTools(api_key="explicit_key")
        assert tools.api_key == "explicit_key"
        mock_client.assert_called_once_with(api_key="explicit_key")


def test_init_all_flag_registers_every_tool():
    with _patch_client():
        tools = ScrapeGraphTools(all=True)
        names = [func.__name__ for func in tools.tools]
        assert set(names) == {"smartscraper", "markdownify", "crawl", "searchscraper", "scrape"}


def test_init_default_registers_smartscraper_only():
    with _patch_client():
        tools = ScrapeGraphTools()
        names = [func.__name__ for func in tools.tools]
        assert names == ["smartscraper"]


def test_init_falls_back_to_markdownify_when_nothing_else_enabled():
    with _patch_client():
        tools = ScrapeGraphTools(enable_smartscraper=False)
        names = [func.__name__ for func in tools.tools]
        # Fallback ensures the toolkit always exposes at least one tool
        assert names == ["markdownify"]


def test_init_explicit_tool_suppresses_markdownify_fallback():
    with _patch_client():
        tools = ScrapeGraphTools(enable_smartscraper=False, enable_scrape=True)
        names = [func.__name__ for func in tools.tools]
        # Only `scrape` is registered — the fallback must NOT add markdownify
        assert names == ["scrape"]


def test_init_deprecated_enable_agentic_crawler_warns_and_is_ignored():
    with _patch_client(), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tools = ScrapeGraphTools(enable_agentic_crawler=True)
        assert any(
            issubclass(w.category, DeprecationWarning) and "enable_agentic_crawler" in str(w.message) for w in caught
        )
        # The v1 method is gone; only the v2 methods remain.
        names = [func.__name__ for func in tools.tools]
        assert "agentic_crawler" not in names


def test_init_instructions_built_for_multi_tool_setup():
    with _patch_client():
        tools = ScrapeGraphTools(all=True)
        assert tools.instructions
        assert "ScrapeGraph tool selection" in tools.instructions


def test_init_skips_instructions_for_single_tool():
    with _patch_client():
        tools = ScrapeGraphTools(enable_smartscraper=True)
        # Only one tool registered -> no adaptive instructions added
        assert not tools.instructions or "ScrapeGraph tool selection" not in (tools.instructions or "")


# ---- smartscraper ----------------------------------------------------------


def test_smartscraper_basic():
    with _patch_client() as mock_client_class:
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
        _, kwargs = mock_client.extract.call_args
        assert kwargs["prompt"] == "extract title"
        assert kwargs["url"] == "https://example.com"
        assert kwargs["fetch_config"] is None


def test_smartscraper_error_handling():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.extract.return_value = _make_api_result(data=None, status="error", error="API Error")

        tools = ScrapeGraphTools(enable_smartscraper=True)
        result = tools.smartscraper("https://example.com", "prompt")

        body = json.loads(result)
        assert "error" in body
        assert "API Error" in body["error"]


# ---- markdownify -----------------------------------------------------------


def test_markdownify_basic():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.results = {"markdown": {"data": "# Title\n\nContent"}}
        mock_client.scrape.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        body = json.loads(result)
        assert body["markdown"] == "# Title\n\nContent"
        assert body["url"] == "https://example.com"
        args, kwargs = mock_client.scrape.call_args
        assert args[0] == "https://example.com"
        assert kwargs["formats"][0].type == "markdown"


def test_markdownify_error_handling():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = _make_api_result(data=None, status="error", error="rate limited")

        tools = ScrapeGraphTools(enable_markdownify=True)
        result = tools.markdownify("https://example.com")

        body = json.loads(result)
        assert "error" in body
        assert "rate limited" in body["error"]


# ---- scrape (raw HTML) -----------------------------------------------------


def test_scrape_basic_functionality():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = json.dumps({"results": {"html": {"data": "<html>test</html>"}}})
        mock_client.scrape.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        assert "<html>test</html>" in result
        args, kwargs = mock_client.scrape.call_args
        assert args[0] == "https://example.com"
        assert kwargs["fetch_config"] is None
        assert kwargs["formats"][0].type == "html"


def test_scrape_with_render_heavy_js():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = "{}"
        mock_client.scrape.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_scrape=True, render_heavy_js=True)
        tools.scrape("https://spa-site.com")

        _, kwargs = mock_client.scrape.call_args
        assert kwargs["fetch_config"].mode == "js"


def test_scrape_error_handling():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.scrape.return_value = _make_api_result(data=None, status="error", error="API Error")

        tools = ScrapeGraphTools(enable_scrape=True)
        result = tools.scrape("https://example.com")

        body = json.loads(result)
        assert "API Error" in body["error"]


# ---- searchscraper ---------------------------------------------------------


def test_searchscraper_basic():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        data = Mock()
        data.model_dump_json.return_value = json.dumps({"results": [{"title": "t", "url": "u"}]})
        mock_client.search.return_value = _make_api_result(data)

        tools = ScrapeGraphTools(enable_searchscraper=True)
        result = tools.searchscraper("What is X?")

        assert json.loads(result) == {"results": [{"title": "t", "url": "u"}]}
        mock_client.search.assert_called_once_with("What is X?")


def test_searchscraper_error_handling():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = _make_api_result(data=None, status="error", error="quota exceeded")

        tools = ScrapeGraphTools(enable_searchscraper=True)
        result = tools.searchscraper("query")

        body = json.loads(result)
        assert "quota exceeded" in body["error"]


# ---- crawl (the polling path) ---------------------------------------------


def _mock_crawl_resource(start_result, *get_results):
    """Build a mock with .start returning start_result and .get returning get_results in order."""
    crawl_resource = Mock()
    crawl_resource.start.return_value = start_result
    crawl_resource.get.side_effect = list(get_results)
    return crawl_resource


def test_crawl_completes_without_polling_when_finished_immediately():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        finished = Mock()
        finished.id = "c1"
        finished.status = "completed"
        finished.model_dump_json.return_value = json.dumps({"pages": [{"url": "https://x.com"}]})
        mock_client.crawl = _mock_crawl_resource(_make_api_result(finished))

        tools = ScrapeGraphTools(enable_crawl=True)
        with patch("agno.tools.scrapegraph.time.sleep") as no_sleep:
            result = tools.crawl(
                "https://x.com",
                prompt="extract",
                schema={"type": "object"},
            )

        # Finished in one shot -> no polling loop entered
        assert not mock_client.crawl.get.called
        assert not no_sleep.called
        assert json.loads(result) == {"pages": [{"url": "https://x.com"}]}


def test_crawl_polls_until_complete():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        running = Mock()
        running.id = "c2"
        running.status = "running"
        still_running = Mock()
        still_running.id = "c2"
        still_running.status = "running"
        done = Mock()
        done.id = "c2"
        done.status = "completed"
        done.model_dump_json.return_value = json.dumps({"status": "completed", "pages": []})

        mock_client.crawl = _mock_crawl_resource(
            _make_api_result(running),
            _make_api_result(still_running),
            _make_api_result(done),
        )

        tools = ScrapeGraphTools(enable_crawl=True)
        with patch("agno.tools.scrapegraph.time.sleep") as slept:
            result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        # Polled twice before completion
        assert mock_client.crawl.get.call_count == 2
        assert slept.call_count == 2
        # Sleeps use the module's poll interval constant
        for call in slept.call_args_list:
            assert call.args[0] == _CRAWL_POLL_INTERVAL_SECONDS
        assert json.loads(result)["status"] == "completed"


def test_crawl_times_out_and_returns_error():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        running = Mock()
        running.id = "c3"
        running.status = "running"
        mock_client.crawl = Mock()
        mock_client.crawl.start.return_value = _make_api_result(running)
        mock_client.crawl.get.return_value = _make_api_result(running)

        # Fake time progression: first call = t0, next calls past the deadline.
        times = iter([0.0, _CRAWL_MAX_WAIT_SECONDS + 1])
        with (
            patch("agno.tools.scrapegraph.time.monotonic", side_effect=lambda: next(times)),
            patch("agno.tools.scrapegraph.time.sleep"),
        ):
            tools = ScrapeGraphTools(enable_crawl=True)
            result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        body = json.loads(result)
        assert "error" in body
        assert "timed out" in body["error"].lower()
        assert body["crawl_id"] == "c3"


def test_crawl_error_status_returns_error_json():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.crawl = Mock()
        mock_client.crawl.start.return_value = _make_api_result(data=None, status="error", error="bad schema")

        tools = ScrapeGraphTools(enable_crawl=True)
        result = tools.crawl("https://x.com", prompt="p", schema={"type": "object"})

        body = json.loads(result)
        assert "bad schema" in body["error"]


def test_crawl_deprecated_kwargs_warn():
    with _patch_client() as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        finished = Mock()
        finished.id = "c4"
        finished.status = "completed"
        finished.model_dump_json.return_value = "{}"
        mock_client.crawl = _mock_crawl_resource(_make_api_result(finished))

        tools = ScrapeGraphTools(enable_crawl=True)
        with (
            warnings.catch_warnings(record=True) as caught,
            patch("agno.tools.scrapegraph.time.sleep"),
        ):
            warnings.simplefilter("always")
            tools.crawl(
                "https://x.com",
                prompt="p",
                schema={"type": "object"},
                cache_website=True,
                use_session=False,
            )

        messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        assert any("cache_website" in m and "use_session" in m for m in messages)


# ---- tool filtering --------------------------------------------------------


def test_tool_selection():
    with _patch_client():
        tools = ScrapeGraphTools(enable_scrape=True, enable_smartscraper=True, enable_markdownify=False)
        names = [func.__name__ for func in tools.tools]
        assert "scrape" in names
        assert "smartscraper" in names
        assert "markdownify" not in names
