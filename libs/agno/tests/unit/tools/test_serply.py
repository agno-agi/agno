import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.serply import SerplyTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure SERPLY_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("SERPLY_API_KEY", raising=False)


@pytest.fixture
def api_tools():
    """SerplyTools with a known API key for testing."""
    return SerplyTools(api_key="test_key", num_results=5)


def _mock_response(payload):
    mock = Mock(spec=requests.Response)
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_search_response():
    return _mock_response(
        {
            "results": [
                {
                    "title": "Result 1",
                    "link": "http://example.com",
                    "description": "Snippet 1",
                    "position": 1,
                    "realPosition": 1,
                    "result_type": "organic",
                    "metadata": {"display_url": "example.com"},
                }
            ],
            "related_searches": [{"title": "related query"}],
            "total": 1,
        }
    )


@pytest.fixture
def mock_news_response():
    return _mock_response(
        {
            "entries": [
                {
                    "title": "Breaking News",
                    "link": "http://news.example.com",
                    "source": {"href": "https://example.com", "title": "Example News"},
                    "published": "Mon, 24 Aug 2026 17:57:33 GMT",
                    "summary": "<ol><li>html</li></ol>",
                }
            ]
        }
    )


@pytest.fixture
def mock_scholar_response():
    return _mock_response(
        {
            "articles": [
                {
                    "title": "A Paper",
                    "link": "http://arxiv.org/abs/1234.5678",
                    "description": "A. Author, B. Author - Journal, 2024",
                    "author": {"names": "A. Author, B. Author - Journal, 2024", "authors": []},
                    "extras": {"citations": {"count": 42, "link": "http://cites.example.com"}},
                    "doc": {"link": "https://arxiv.org/pdf/1234.5678", "type": "PDF"},
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


def test_init_without_api_key(monkeypatch):
    monkeypatch.delenv("SERPLY_API_KEY", raising=False)
    tools = SerplyTools()
    assert tools.api_key is None


def test_init_with_env_var(monkeypatch):
    monkeypatch.setenv("SERPLY_API_KEY", "env_key")
    tools = SerplyTools()
    assert tools.api_key == "env_key"


def test_init_constructor_key_overrides_env(monkeypatch):
    monkeypatch.setenv("SERPLY_API_KEY", "env_key")
    tools = SerplyTools(api_key="direct_key")
    assert tools.api_key == "direct_key"


def test_init_default_params():
    tools = SerplyTools(api_key="k")
    assert tools.num_results == 10
    assert tools.timeout == 30


def test_init_only_web_enabled_by_default():
    tools = SerplyTools(api_key="k")
    names = [f.name for f in tools.functions.values()]
    assert names == ["search_web"]


def test_init_all_enabled():
    tools = SerplyTools(api_key="k", all=True)
    names = [f.name for f in tools.functions.values()]
    assert names == ["search_web", "search_news", "search_scholar"]


def test_init_select_tools():
    tools = SerplyTools(api_key="k", search_web=False, search_scholar=True)
    names = [f.name for f in tools.functions.values()]
    assert names == ["search_scholar"]


# ---------------------------------------------------------------------------
# _make_request
# ---------------------------------------------------------------------------


def test_make_request_no_api_key():
    tools = SerplyTools()
    result = tools._make_request("search", {"q": "x"})
    assert "error" in result


def test_make_request_sends_key_header_and_timeout(api_tools, mock_search_response):
    with patch("requests.get", return_value=mock_search_response) as mock_get:
        api_tools._make_request("search", {"q": "x", "num": 5})
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.serply.io/v1/search/"
    assert kwargs["headers"]["X-Api-Key"] == "test_key"
    assert kwargs["params"] == {"q": "x", "num": 5}
    assert kwargs["timeout"] == 30


def test_make_request_http_error(api_tools):
    mock_resp = Mock(spec=requests.Response)
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("401 Unauthorized")
    with patch("requests.get", return_value=mock_resp):
        result = api_tools._make_request("search", {"q": "x"})
    assert "HTTP error" in result["error"]


def test_make_request_connection_error(api_tools):
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("No route to host")):
        result = api_tools._make_request("search", {"q": "x"})
    assert "No route to host" in result["error"]


def test_make_request_invalid_json(api_tools):
    mock_resp = Mock(spec=requests.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.side_effect = ValueError("bad json")
    with patch("requests.get", return_value=mock_resp):
        result = api_tools._make_request("search", {"q": "x"})
    assert "Invalid JSON" in result["error"]


# ---------------------------------------------------------------------------
# search_web
# ---------------------------------------------------------------------------


def test_search_web_empty_query(api_tools):
    result = json.loads(api_tools.search_web(""))
    assert "error" in result


def test_search_web_no_api_key():
    tools = SerplyTools()
    result = json.loads(tools.search_web("test"))
    assert "error" in result


def test_search_web_success(api_tools, mock_search_response):
    with patch("requests.get", return_value=mock_search_response):
        result = json.loads(api_tools.search_web("test"))
    assert result["results"] == [
        {"position": 1, "title": "Result 1", "link": "http://example.com", "description": "Snippet 1"}
    ]
    assert result["related_searches"] == [{"title": "related query"}]


def test_search_web_uses_instance_num_results(api_tools, mock_search_response):
    with patch("requests.get", return_value=mock_search_response) as mock_get:
        api_tools.search_web("test")
    assert mock_get.call_args.kwargs["params"] == {"q": "test", "num": 5}


def test_search_web_custom_num_results(api_tools, mock_search_response):
    with patch("requests.get", return_value=mock_search_response) as mock_get:
        api_tools.search_web("test", num_results=3)
    assert mock_get.call_args.kwargs["params"]["num"] == 3


def test_search_web_zero_num_results_is_respected(api_tools, mock_search_response):
    with patch("requests.get", return_value=mock_search_response) as mock_get:
        api_tools.search_web("test", num_results=0)
    assert mock_get.call_args.kwargs["params"]["num"] == 0


def test_search_web_error_response(api_tools):
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("down")):
        result = json.loads(api_tools.search_web("test"))
    assert result == {"error": "down"}


# ---------------------------------------------------------------------------
# search_news
# ---------------------------------------------------------------------------


def test_search_news_empty_query(api_tools):
    result = json.loads(api_tools.search_news(""))
    assert "error" in result


def test_search_news_success(api_tools, mock_news_response):
    with patch("requests.get", return_value=mock_news_response) as mock_get:
        result = json.loads(api_tools.search_news("test"))
    assert mock_get.call_args.args[0] == "https://api.serply.io/v1/news/"
    assert result["news_results"] == [
        {
            "title": "Breaking News",
            "link": "http://news.example.com",
            "source": "Example News",
            "published": "Mon, 24 Aug 2026 17:57:33 GMT",
        }
    ]


def test_search_news_trims_to_num_results(api_tools):
    entries = [{"title": f"t{i}", "link": f"l{i}"} for i in range(20)]
    with patch("requests.get", return_value=_mock_response({"entries": entries})):
        result = json.loads(api_tools.search_news("test", num_results=3))
    assert [r["title"] for r in result["news_results"]] == ["t0", "t1", "t2"]


def test_search_news_missing_source(api_tools):
    with patch("requests.get", return_value=_mock_response({"entries": [{"title": "t", "link": "l"}]})):
        result = json.loads(api_tools.search_news("test"))
    assert result["news_results"][0]["source"] is None


# ---------------------------------------------------------------------------
# search_scholar
# ---------------------------------------------------------------------------


def test_search_scholar_empty_query(api_tools):
    result = json.loads(api_tools.search_scholar(""))
    assert "error" in result


def test_search_scholar_success(api_tools, mock_scholar_response):
    with patch("requests.get", return_value=mock_scholar_response) as mock_get:
        result = json.loads(api_tools.search_scholar("test"))
    assert mock_get.call_args.args[0] == "https://api.serply.io/v1/scholar/"
    assert result["scholar_results"] == [
        {
            "title": "A Paper",
            "link": "http://arxiv.org/abs/1234.5678",
            "description": "A. Author, B. Author - Journal, 2024",
            "authors": "A. Author, B. Author - Journal, 2024",
            "citations": 42,
            "pdf": "https://arxiv.org/pdf/1234.5678",
        }
    ]


def test_search_scholar_missing_optional_fields(api_tools):
    payload = {"articles": [{"title": "t", "link": "l", "doc": None, "extras": {}}]}
    with patch("requests.get", return_value=_mock_response(payload)):
        result = json.loads(api_tools.search_scholar("test"))
    item = result["scholar_results"][0]
    assert item["authors"] is None
    assert item["citations"] is None
    assert item["pdf"] is None
