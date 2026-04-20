"""Tests for error handling in WebSearchTools and WikipediaTools.

Regression tests for #7383: both tools should return a descriptive error
string instead of raising unhandled exceptions when the underlying API fails.
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


class TestWebSearchToolsErrorHandling:
    """WebSearchTools should catch exceptions and return error JSON."""

    def test_web_search_returns_error_on_exception(self):
        """web_search() returns error JSON when DDGS raises."""
        from agno.tools.websearch import WebSearchTools

        tools = WebSearchTools()

        with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.text.side_effect = ConnectionError("Network unreachable")
            mock_ddgs_cls.return_value = mock_ctx

            result = tools.web_search("test query")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Network unreachable" in parsed["error"]

    def test_search_news_returns_error_on_exception(self):
        """search_news() returns error JSON when DDGS raises."""
        from agno.tools.websearch import WebSearchTools

        tools = WebSearchTools()

        with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.news.side_effect = TimeoutError("Request timed out")
            mock_ddgs_cls.return_value = mock_ctx

            result = tools.search_news("test query")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"].lower()

    def test_web_search_returns_valid_json_on_success(self):
        """web_search() still returns valid JSON on success."""
        from agno.tools.websearch import WebSearchTools

        tools = WebSearchTools()

        with patch("agno.tools.websearch.DDGS") as mock_ddgs_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.text.return_value = [{"title": "Test", "href": "https://test.com"}]
            mock_ddgs_cls.return_value = mock_ctx

            result = tools.web_search("test query")

        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert parsed[0]["title"] == "Test"


# Wikipedia tests require the `wikipedia` package to be installed because
# agno.tools.wikipedia raises ImportError at module level when it's missing.
# If the package is unavailable, these tests are skipped automatically.
wikipedia = pytest.importorskip("wikipedia", reason="wikipedia package not installed")


class TestWikipediaToolsErrorHandling:
    """WikipediaTools should catch exceptions and return error strings."""

    def test_search_wikipedia_returns_error_on_exception(self):
        """search_wikipedia() returns error JSON when wikipedia raises."""
        from agno.tools.wikipedia import WikipediaTools

        tools = WikipediaTools()

        with patch("wikipedia.summary", side_effect=Exception("Page not found")):
            result = tools.search_wikipedia("NonExistentTopic")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Page not found" in parsed["error"]

    def test_search_wikipedia_handles_disambiguation(self):
        """search_wikipedia() returns disambiguation options when ambiguous."""
        from agno.tools.wikipedia import WikipediaTools
        from wikipedia.exceptions import DisambiguationError

        tools = WikipediaTools()

        with patch("wikipedia.summary", side_effect=DisambiguationError("Test", ["Option A", "Option B"], "Test")):
            result = tools.search_wikipedia("Python")

        parsed = json.loads(result)
        assert "disambiguation" in parsed
        assert "Option A" in parsed["options"]

    def test_search_wikipedia_returns_valid_json_on_success(self):
        """search_wikipedia() returns valid JSON on success."""
        from agno.tools.wikipedia import WikipediaTools

        tools = WikipediaTools()

        with patch("wikipedia.summary", return_value="Python is a programming language."):
            result = tools.search_wikipedia("Python")

        parsed = json.loads(result)
        assert "content" in parsed
        assert "Python is a programming language" in parsed["content"]
