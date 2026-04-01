"""Integration tests for SeltzTools — requires SELTZ_API_KEY env var."""

import json
import os

import pytest

pytest.importorskip("seltz")

from agno.tools.seltz import SeltzTools

pytestmark = pytest.mark.skipif(
    not os.environ.get("SELTZ_API_KEY"),
    reason="SELTZ_API_KEY not set",
)


@pytest.fixture
def seltz_tools():
    return SeltzTools(max_documents=3, show_results=False)


def test_search_returns_documents(seltz_tools):
    """Search returns valid JSON with document URLs and content."""
    result = seltz_tools.search_seltz("latest developments in AI")
    data = json.loads(result)

    assert len(data) > 0
    for doc in data:
        assert "url" in doc
        assert doc["url"].startswith("http")


def test_search_respects_max_documents(seltz_tools):
    """Search respects the max_documents parameter."""
    result = seltz_tools.search_seltz("python programming", max_documents=2)
    data = json.loads(result)

    assert len(data) <= 2


def test_search_with_context(seltz_tools):
    """Search with context parameter does not error."""
    result = seltz_tools.search_seltz(
        "web frameworks",
        context="looking for modern Python web frameworks",
    )
    data = json.loads(result)

    assert len(data) > 0


def test_search_empty_query(seltz_tools):
    """Empty query returns an error string, not an exception."""
    result = seltz_tools.search_seltz("")
    assert "Error" in result


def test_search_invalid_max_documents(seltz_tools):
    """Zero max_documents returns an error string, not an exception."""
    result = seltz_tools.search_seltz("test", max_documents=0)
    assert "Error" in result
