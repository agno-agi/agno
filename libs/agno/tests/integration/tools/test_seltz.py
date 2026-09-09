"""Integration tests for SeltzTools — requires SELTZ_API_KEY env var."""

import json
import os
from inspect import signature

import pytest

pytest.importorskip("seltz")

from agno.tools.seltz import SeltzTools

pytestmark = pytest.mark.skipif(
    not os.environ.get("SELTZ_API_KEY"),
    reason="SELTZ_API_KEY not set",
)


@pytest.fixture
def seltz_tools():
    return SeltzTools(max_results=3, show_results=False)


def _client_supports_search_parameter(seltz_tools: SeltzTools, parameter_name: str) -> bool:
    if not seltz_tools.client:
        return False

    return parameter_name in signature(seltz_tools.client.search).parameters


def test_search_returns_documents(seltz_tools):
    """Search returns valid JSON with document URLs and content."""
    result = seltz_tools.search_seltz("latest developments in AI")
    data = json.loads(result)

    assert len(data) > 0
    for doc in data:
        assert "url" in doc
        assert doc["url"].startswith("http")


def test_search_respects_max_results(seltz_tools):
    """Search respects the max_results parameter."""
    result = seltz_tools.search_seltz("python programming", max_results=2)
    data = json.loads(result)

    assert len(data) <= 2


def test_search_with_domain_filter(seltz_tools):
    """Search with a current SDK filter parameter does not error."""
    if not _client_supports_search_parameter(seltz_tools, "include_domains"):
        pytest.skip("Installed seltz SDK does not support include_domains.")

    result = seltz_tools.search_seltz(
        "python programming",
        include_domains=["python.org"],
    )
    data = json.loads(result)

    assert isinstance(data, list)


def test_search_empty_query(seltz_tools):
    """Empty query returns an error string, not an exception."""
    result = seltz_tools.search_seltz("")
    assert "Error" in result


def test_search_invalid_max_results(seltz_tools):
    """Zero max_results returns an error string, not an exception."""
    result = seltz_tools.search_seltz("test", max_results=0)
    assert "Error" in result
