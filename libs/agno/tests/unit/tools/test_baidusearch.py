"""Unit tests for BaiduSearchTools class."""

import json
from unittest.mock import patch

import pytest

pytest.importorskip("baidusearch")
pytest.importorskip("pycountry")

from agno.tools.baidusearch import BaiduSearchTools  # noqa: E402


def get_num_results_sent(mock_search):
    """Return the num_results value sent to the baidusearch client."""
    return mock_search.call_args.kwargs["num_results"]


def test_baidu_search_uses_fixed_max_results():
    """Test that fixed_max_results set on the toolkit reaches the search call."""
    tools = BaiduSearchTools(fixed_max_results=3)

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = []
        tools.baidu_search("test query", max_results=10)

    assert get_num_results_sent(mock_search) == 3


def test_baidu_search_fixed_max_results_zero_is_honored():
    """A fixed_max_results of 0 must reach the search call instead of falling back to the argument."""
    tools = BaiduSearchTools(fixed_max_results=0)

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = []
        tools.baidu_search("test query", max_results=5)

    assert get_num_results_sent(mock_search) == 0


def test_baidu_search_explicit_max_results_zero_is_honored():
    """An explicit max_results of 0 with no fixed value must reach the search call."""
    tools = BaiduSearchTools()

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = []
        tools.baidu_search("test query", max_results=0)

    assert get_num_results_sent(mock_search) == 0


def test_baidu_search_defaults_to_five():
    """Test that max_results falls back to 5 when not configured anywhere."""
    tools = BaiduSearchTools()

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = []
        tools.baidu_search("test query")

    assert get_num_results_sent(mock_search) == 5


def test_baidu_search_output_format():
    """Test that results are serialized as JSON with title, url, abstract and rank fields."""
    tools = BaiduSearchTools()

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = [{"title": "T", "url": "U", "abstract": "A"}]
        result = tools.baidu_search("test query")

    assert json.loads(result) == [{"title": "T", "url": "U", "abstract": "A", "rank": "1"}]


@pytest.mark.parametrize(
    "title, abstract",
    [
        ("百度一下，你就知道", "全球领先的中文搜索引擎"),
        ("臺北101 - 維基百科", "臺北101是位於臺灣臺北市信義區的摩天大樓"),
        ("Agno 中文文档", "Build agents with Agno 快速入门"),
    ],
    ids=["simplified", "traditional", "mixed"],
)
def test_baidu_search_keeps_non_ascii_text_unescaped(title, abstract):
    """Test that Chinese text in results is returned unescaped and the output remains valid JSON."""
    tools = BaiduSearchTools()

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = [{"title": title, "url": "https://www.baidu.com", "abstract": abstract}]
        result = tools.baidu_search(title)

    assert title in result
    assert abstract in result
    assert "\\u" not in result
    assert json.loads(result) == [{"title": title, "url": "https://www.baidu.com", "abstract": abstract, "rank": "1"}]


def test_baidu_search_fixed_language_wins():
    """Test that fixed_language set on the toolkit overrides the per-call language."""
    tools = BaiduSearchTools(fixed_language="english")

    with patch("agno.tools.baidusearch.search") as mock_search:
        mock_search.return_value = []
        tools.baidu_search("test query", language="en")

    # The non-2-letter fixed language is resolved through pycountry to its alpha-2 code
    assert mock_search.call_args.kwargs["keyword"] == "test query"
    assert mock_search.call_args.kwargs["num_results"] == 5
