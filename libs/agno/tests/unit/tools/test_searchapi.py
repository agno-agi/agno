import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.searchapi import SearchApiTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure SEARCHAPI_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("SEARCHAPI_API_KEY", raising=False)


@pytest.fixture
def api_tools():
    """SearchApiTools with a known API key for testing."""
    return SearchApiTools(api_key="test_key", num_results=5)


@pytest.fixture
def mock_google_response():
    mock = Mock(spec=requests.Response)
    mock.json.return_value = {
        "organic_results": [
            {"position": 1, "title": "Result 1", "link": "http://example.com", "snippet": "Snippet 1", "source": "Example"}
        ],
        "knowledge_graph": None,
        "related_questions": [],
        "search_information": {"total_results": 1, "time_taken_displayed": 0.5},
    }
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_news_response():
    mock = Mock(spec=requests.Response)
    mock.json.return_value = {
        "news_results": [
            {
                "position": 1,
                "title": "Breaking News",
                "link": "http://news.example.com",
                "source": {"name": "BBC"},
                "date": "2 hours ago",
                "snippet": "News snippet",
                "thumbnail": "http://thumb.example.com",
            }
        ]
    }
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_images_response():
    mock = Mock(spec=requests.Response)
    mock.json.return_value = {
        "image_results": [
            {
                "position": 1,
                "title": "Image 1",
                "link": "http://image.example.com",
                "original": "http://original.example.com/img.jpg",
                "thumbnail": "http://thumb.example.com/img.jpg",
                "source": "example.com",
            }
        ]
    }
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_youtube_response():
    mock = Mock(spec=requests.Response)
    mock.json.return_value = {
        "videos": [
            {
                "position": 1,
                "title": "Video 1",
                "link": "https://www.youtube.com/watch?v=abc123",
                "channel": {"name": "Test Channel"},
                "duration": "5:30",
                "views": 10000,
                "description": "A test video",
                "thumbnail": {"static": "http://thumb.youtube.com/img.jpg"},
            }
        ]
    }
    mock.raise_for_status.return_value = None
    return mock


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


def test_init_without_api_key(monkeypatch):
    monkeypatch.delenv("SEARCHAPI_API_KEY", raising=False)
    tools = SearchApiTools()
    assert tools.api_key is None


def test_init_with_env_var(monkeypatch):
    monkeypatch.setenv("SEARCHAPI_API_KEY", "env_key")
    tools = SearchApiTools()
    assert tools.api_key == "env_key"


def test_init_with_constructor_key():
    tools = SearchApiTools(api_key="direct_key")
    assert tools.api_key == "direct_key"


def test_init_constructor_key_overrides_env(monkeypatch):
    monkeypatch.setenv("SEARCHAPI_API_KEY", "env_key")
    tools = SearchApiTools(api_key="direct_key")
    assert tools.api_key == "direct_key"


def test_init_default_params():
    tools = SearchApiTools(api_key="test_key")
    assert tools.num_results == 5
    assert tools.timeout == 30


def test_init_custom_params():
    tools = SearchApiTools(api_key="test_key", num_results=10, timeout=60)
    assert tools.num_results == 10
    assert tools.timeout == 60


def test_init_only_google_enabled_by_default():
    tools = SearchApiTools(api_key="test_key")
    tool_names = [t.name for t in tools.functions.values()]
    assert "search_google" in tool_names
    assert "search_news" not in tool_names
    assert "search_images" not in tool_names
    assert "search_youtube" not in tool_names


def test_init_all_enabled():
    tools = SearchApiTools(api_key="test_key", all=True)
    tool_names = [t.name for t in tools.functions.values()]
    assert "search_google" in tool_names
    assert "search_news" in tool_names
    assert "search_images" in tool_names
    assert "search_youtube" in tool_names


# ---------------------------------------------------------------------------
# _make_request: no API key
# ---------------------------------------------------------------------------


def test_make_request_no_api_key():
    tools = SearchApiTools()
    result = tools._make_request({"engine": "google", "q": "test"})
    assert "error" in result


def test_make_request_does_not_mutate_params(api_tools, mock_google_response):
    original_params = {"engine": "google", "q": "test"}
    params_copy = dict(original_params)
    with patch("requests.get", return_value=mock_google_response):
        api_tools._make_request(original_params)
    assert original_params == params_copy


def test_make_request_uses_configured_timeout(api_tools, mock_google_response):
    with patch("requests.get", return_value=mock_google_response) as mock_get:
        api_tools._make_request({"engine": "google", "q": "test"})
        _, kwargs = mock_get.call_args
        assert kwargs["timeout"] == api_tools.timeout


def test_make_request_http_error(api_tools):
    mock_resp = Mock(spec=requests.Response)
    mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
    with patch("requests.get", return_value=mock_resp):
        result = api_tools._make_request({"engine": "google", "q": "test"})
    assert "error" in result
    assert "404 Not Found" in result["error"]


def test_make_request_connection_error(api_tools):
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("No route to host")):
        result = api_tools._make_request({"engine": "google", "q": "test"})
    assert "error" in result


def test_make_request_invalid_json(api_tools):
    mock_resp = Mock(spec=requests.Response)
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.side_effect = ValueError("No JSON object")
    with patch("requests.get", return_value=mock_resp):
        result = api_tools._make_request({"engine": "google", "q": "test"})
    assert "error" in result
    assert "Invalid JSON response" in result["error"]


# ---------------------------------------------------------------------------
# search_google
# ---------------------------------------------------------------------------


def test_search_google_empty_query(api_tools):
    result = json.loads(api_tools.search_google(""))
    assert "error" in result


def test_search_google_no_api_key():
    tools = SearchApiTools()
    result = json.loads(tools.search_google("python"))
    assert "error" in result


def test_search_google_success(api_tools, mock_google_response):
    with patch("requests.get", return_value=mock_google_response):
        result = json.loads(api_tools.search_google("python"))
    assert "organic_results" in result
    assert result["organic_results"][0]["title"] == "Result 1"
    assert result["organic_results"][0]["link"] == "http://example.com"


def test_search_google_correct_params_sent(api_tools, mock_google_response):
    with patch("requests.get", return_value=mock_google_response) as mock_get:
        api_tools.search_google("python", num_results=3, location="London", language="en")
    params = mock_get.call_args[1]["params"]
    assert params["engine"] == "google"
    assert params["q"] == "python"
    assert params["num"] == 3
    assert params["location"] == "London"
    assert params["hl"] == "en"
    assert params["api_key"] == "test_key"


def test_search_google_uses_instance_num_results(api_tools, mock_google_response):
    with patch("requests.get", return_value=mock_google_response) as mock_get:
        api_tools.search_google("python")
    params = mock_get.call_args[1]["params"]
    assert params["num"] == 5


# ---------------------------------------------------------------------------
# search_news
# ---------------------------------------------------------------------------


def test_search_news_empty_query(api_tools):
    result = json.loads(api_tools.search_news(""))
    assert "error" in result


def test_search_news_success(api_tools, mock_news_response):
    with patch("requests.get", return_value=mock_news_response):
        result = json.loads(api_tools.search_news("AI news"))
    assert "news_results" in result
    assert result["news_results"][0]["title"] == "Breaking News"
    assert result["news_results"][0]["source"] == "BBC"


def test_search_news_correct_params_sent(api_tools, mock_news_response):
    with patch("requests.get", return_value=mock_news_response) as mock_get:
        api_tools.search_news("AI news", language="en", country="us")
    params = mock_get.call_args[1]["params"]
    assert params["engine"] == "google_news"
    assert params["q"] == "AI news"
    assert params["hl"] == "en"
    assert params["gl"] == "us"


# ---------------------------------------------------------------------------
# search_images
# ---------------------------------------------------------------------------


def test_search_images_empty_query(api_tools):
    result = json.loads(api_tools.search_images(""))
    assert "error" in result


def test_search_images_success(api_tools, mock_images_response):
    with patch("requests.get", return_value=mock_images_response):
        result = json.loads(api_tools.search_images("cats"))
    assert "image_results" in result
    assert result["image_results"][0]["title"] == "Image 1"


def test_search_images_correct_params_sent(api_tools, mock_images_response):
    with patch("requests.get", return_value=mock_images_response) as mock_get:
        api_tools.search_images("cats", safe_search="active")
    params = mock_get.call_args[1]["params"]
    assert params["engine"] == "google_images"
    assert params["q"] == "cats"
    assert params["safe"] == "active"


# ---------------------------------------------------------------------------
# search_youtube
# ---------------------------------------------------------------------------


def test_search_youtube_empty_query(api_tools):
    result = json.loads(api_tools.search_youtube(""))
    assert "error" in result


def test_search_youtube_success(api_tools, mock_youtube_response):
    with patch("requests.get", return_value=mock_youtube_response):
        result = json.loads(api_tools.search_youtube("python tutorial"))
    assert "video_results" in result
    assert result["video_results"][0]["title"] == "Video 1"
    assert result["video_results"][0]["channel"] == "Test Channel"
    assert result["video_results"][0]["thumbnail"] == "http://thumb.youtube.com/img.jpg"


def test_search_youtube_uses_q_param(api_tools, mock_youtube_response):
    with patch("requests.get", return_value=mock_youtube_response) as mock_get:
        api_tools.search_youtube("python tutorial")
    params = mock_get.call_args[1]["params"]
    assert params["engine"] == "youtube"
    assert params["q"] == "python tutorial"
    assert "search_query" not in params


def test_search_youtube_empty_results(api_tools):
    mock = Mock(spec=requests.Response)
    mock.json.return_value = {"videos": []}
    mock.raise_for_status.return_value = None
    with patch("requests.get", return_value=mock):
        result = json.loads(api_tools.search_youtube("xyznotfound123"))
    assert result["video_results"] == []
