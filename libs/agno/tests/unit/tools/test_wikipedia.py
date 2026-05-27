import json
from unittest.mock import patch

import pytest

wikipedia = pytest.importorskip("wikipedia")

from wikipedia.exceptions import DisambiguationError, PageError  # noqa: E402

from agno.tools.wikipedia import WikipediaTools  # noqa: E402


def test_init_defaults():
    tools = WikipediaTools()
    assert tools.auto_suggest is True
    assert tools.knowledge is None


def test_init_auto_suggest_false():
    tools = WikipediaTools(auto_suggest=False)
    assert tools.auto_suggest is False


def test_search_happy_path():
    tools = WikipediaTools()
    with patch("wikipedia.summary", return_value="Nvidia Corporation is a technology company.") as mock_summary:
        result = tools.search_wikipedia("Nvidia")
        data = json.loads(result)
        assert data["name"] == "Nvidia"
        assert "Nvidia Corporation" in data["content"]
        mock_summary.assert_called_once_with("Nvidia", auto_suggest=True)


def test_search_auto_suggest_false_passed_through():
    tools = WikipediaTools(auto_suggest=False)
    with patch("wikipedia.summary", return_value="Test content") as mock_summary:
        tools.search_wikipedia("Test")
        mock_summary.assert_called_once_with("Test", auto_suggest=False)


def test_search_disambiguation_error():
    tools = WikipediaTools()
    error = DisambiguationError("Nvidia", ["Nvidia Corporation", "Nvidia Shield", "Nvidia Tegra"])
    with patch("wikipedia.summary", side_effect=error):
        result = tools.search_wikipedia("Nvidia")
        data = json.loads(result)
        assert data["disambiguation"] == "Nvidia"
        assert "Nvidia Corporation" in data["options"]
        assert len(data["options"]) == 3


def test_search_page_error():
    tools = WikipediaTools()
    with patch("wikipedia.summary", side_effect=PageError(pageid="nonexistent_page_xyz")):
        result = tools.search_wikipedia("nonexistent_page_xyz")
        data = json.loads(result)
        assert "error" in data


def test_search_generic_exception():
    tools = WikipediaTools()
    with patch("wikipedia.summary", side_effect=ConnectionError("network down")):
        result = tools.search_wikipedia("Test")
        data = json.loads(result)
        assert "network down" in data["error"]


def test_disambiguation_returns_all_options():
    many_options = [f"Option {i}" for i in range(30)]
    tools = WikipediaTools()
    error = DisambiguationError("Mercury", many_options)
    with patch("wikipedia.summary", side_effect=error):
        result = tools.search_wikipedia("Mercury")
        data = json.loads(result)
        assert len(data["options"]) == 30
