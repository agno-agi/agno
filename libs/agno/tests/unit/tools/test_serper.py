import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.serper import SerperTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure SERPER_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("SERPER_API_KEY", raising=False)


@pytest.fixture
def api_tools():
    """SerperTools with a known API key and custom settings for testing."""
    return SerperTools(
        api_key="test_key",
        location="us",
        language="en",
        num_results=5,
        date_range="qdr:d",  # Last day
    )


@pytest.fixture
def mock_search_response():
    """Mock a successful Serper API search response."""
    mock = Mock(spec=requests.Response)
    mock.text = '{"organic": [{"title": "Test Result", "link": "http://example.com"}]}'
    mock.json.return_value = {"organic": [{"title": "Test Result", "link": "http://example.com"}]}
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_news_response():
    """Mock a successful Serper API news response."""
    mock = Mock(spec=requests.Response)
    mock.text = '{"news": [{"title": "Breaking News", "link": "http://news.example.com", "date": "2 hours ago"}]}'
    mock.json.return_value = {
        "news": [{"title": "Breaking News", "link": "http://news.example.com", "date": "2 hours ago"}]
    }
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_scholar_response():
    """Mock a successful Serper API scholar response."""
    mock = Mock(spec=requests.Response)
    mock.text = (
        '{"organic": [{"title": "Research Paper", "link": "http://scholar.example.com", "authors": ["Dr. Smith"]}]}'
    )
    mock.json.return_value = {
        "organic": [{"title": "Research Paper", "link": "http://scholar.example.com", "authors": ["Dr. Smith"]}]
    }
    mock.raise_for_status.return_value = None
    return mock


@pytest.fixture
def mock_scrape_response():
    """Mock a successful Serper API scrape response."""
    mock = Mock(spec=requests.Response)
    mock.text = '{"text": "Scraped content", "title": "Example Page"}'
    mock.json.return_value = {"text": "Scraped content", "title": "Example Page"}
    mock.raise_for_status.return_value = None
    return mock


# Initialization Tests
def test_init_without_api_key_and_env(monkeypatch):
    """If no api_key argument and no SERPER_API_KEY in env, api_key should be None."""
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    tools = SerperTools()
    assert tools.api_key is None


def test_init_with_env_var(monkeypatch):
    """If SERPER_API_KEY is set in the environment, it is picked up."""
    monkeypatch.setenv("SERPER_API_KEY", "env_key")
    tools = SerperTools(api_key=None)
    assert tools.api_key == "env_key"


def test_init_with_custom_params():
    """Test initialization with custom parameters."""
    tools = SerperTools(
        api_key="test_key",
        location="uk",
        language="fr",
        num_results=15,
        date_range="qdr:w",
    )
    assert tools.api_key == "test_key"
    assert tools.location == "uk"
    assert tools.language == "fr"
    assert tools.num_results == 15
    assert tools.date_range == "qdr:w"


# Search Tests
def test_search_no_api_key():
    """Calling search without any API key returns an error message."""
    tools = SerperTools(api_key=None)
    result = tools.search_web("anything")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a Serper API key" in result_json["error"]


def test_search_empty_query(api_tools):
    """Calling search with an empty query returns an error message."""
    result = api_tools.search_web("")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a query to search for" in result_json["error"]


def test_search_success(api_tools, mock_search_response):
    """A successful search should return the raw response.text and call requests.request correctly."""
    with patch("requests.request", return_value=mock_search_response) as mock_req:
        result = api_tools.search_web("pytest testing")
        assert result == mock_search_response.text

        mock_req.assert_called_once_with(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps({"q": "pytest testing", "num": 5, "tbs": "qdr:d", "gl": "us", "hl": "en"}),
        )


def test_search_with_custom_num_results(api_tools, mock_search_response):
    """Overriding the num_results parameter should be respected in the request payload."""
    with patch("requests.request", return_value=mock_search_response) as mock_req:
        result = api_tools.search_web("pytest testing", num_results=20)
        assert result == mock_search_response.text

        expected_payload = {
            "q": "pytest testing",
            "num": 20,
            "tbs": "qdr:d",
            "gl": "us",
            "hl": "en",
        }
        mock_req.assert_called_once_with(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps(expected_payload),
        )


def test_search_exception(api_tools):
    """If requests.request raises, search should catch and return an error string."""
    with patch("requests.request", side_effect=Exception("Network failure")):
        result = api_tools.search_web("failure test")
        result_json = json.loads(result)
        assert "error" in result_json
        assert "Network failure" in result_json["error"]


# News Search Tests
def test_search_news_no_api_key():
    """Calling search_news without any API key returns an error message."""
    tools = SerperTools(api_key=None)
    result = tools.search_news("tech news")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a Serper API key" in result_json["error"]


def test_search_news_empty_query(api_tools):
    """Calling search_news with an empty query returns an error message."""
    result = api_tools.search_news("")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a query to search for news" in result_json["error"]


def test_search_news_success(api_tools, mock_news_response):
    """A successful news search should return the raw response.text."""
    with patch("requests.request", return_value=mock_news_response) as mock_req:
        result = api_tools.search_news("latest tech news")
        assert result == mock_news_response.text

        expected_payload = {
            "q": "latest tech news",
            "num": 5,
            "tbs": "qdr:d",
            "gl": "us",
            "hl": "en",
        }
        mock_req.assert_called_once_with(
            "POST",
            "https://google.serper.dev/news",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps(expected_payload),
        )


def test_search_news_with_custom_num_results(api_tools, mock_news_response):
    """Overriding num_results in news search should work."""
    with patch("requests.request", return_value=mock_news_response) as mock_req:
        result = api_tools.search_news("tech news", num_results=15)
        assert result == mock_news_response.text

        expected_payload = {"q": "tech news", "num": 15, "tbs": "qdr:d", "gl": "us", "hl": "en"}
        mock_req.assert_called_once()
        call_args = mock_req.call_args
        assert json.loads(call_args[1]["data"]) == expected_payload


def test_search_news_exception(api_tools):
    """If requests.request raises during news search, should catch and return error."""
    with patch("requests.request", side_effect=Exception("API timeout")):
        result = api_tools.search_news("breaking news")
        result_json = json.loads(result)
        assert "error" in result_json
        assert "API timeout" in result_json["error"]


# Scholar Search Tests
def test_search_scholar_no_api_key():
    """Calling search_scholar without any API key returns an error message."""
    tools = SerperTools(api_key=None)
    result = tools.search_scholar("machine learning")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a Serper API key" in result_json["error"]


def test_search_scholar_empty_query(api_tools):
    """Calling search_scholar with an empty query returns an error message."""
    result = api_tools.search_scholar("")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a query to search for academic papers" in result_json["error"]


def test_search_scholar_success(api_tools, mock_scholar_response):
    """A successful scholar search should return the raw response.text."""
    with patch("requests.request", return_value=mock_scholar_response) as mock_req:
        result = api_tools.search_scholar("artificial intelligence")
        assert result == mock_scholar_response.text

        expected_payload = {
            "q": "artificial intelligence",
            "num": 5,
            "tbs": "qdr:d",
            "gl": "us",
            "hl": "en",
        }
        mock_req.assert_called_once_with(
            "POST",
            "https://google.serper.dev/scholar",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps(expected_payload),
        )


def test_search_scholar_exception(api_tools):
    """If requests.request raises during scholar search, should catch and return error."""
    with patch("requests.request", side_effect=Exception("Scholar API error")):
        result = api_tools.search_scholar("quantum computing")
        result_json = json.loads(result)
        assert "error" in result_json
        assert "Scholar API error" in result_json["error"]


# Webpage Scraping Tests
def test_scrape_webpage_no_api_key():
    """Calling scrape_webpage without any API key returns an error message."""
    tools = SerperTools(api_key=None)
    result = tools.scrape_webpage("https://example.com")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a Serper API key" in result_json["error"]


def test_scrape_webpage_empty_url(api_tools):
    """Calling scrape_webpage with an empty URL returns an error message."""
    result = api_tools.scrape_webpage("")
    result_json = json.loads(result)
    assert "error" in result_json
    assert "Please provide a URL to scrape" in result_json["error"]


def test_scrape_webpage_success(api_tools, mock_scrape_response):
    """A successful webpage scrape should return the raw response.text."""
    with patch("requests.request", return_value=mock_scrape_response) as mock_req:
        result = api_tools.scrape_webpage("https://example.com")
        assert result == mock_scrape_response.text

        expected_payload = {
            "url": "https://example.com",
            "includeMarkdown": False,
            "tbs": "qdr:d",
            "gl": "us",
            "hl": "en",
        }
        mock_req.assert_called_once_with(
            "POST",
            "https://scrape.serper.dev",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps(expected_payload),
        )


def test_scrape_webpage_with_markdown(api_tools, mock_scrape_response):
    """Scraping with markdown=True should set includeMarkdown to True."""
    with patch("requests.request", return_value=mock_scrape_response) as mock_req:
        result = api_tools.scrape_webpage("https://example.com", markdown=True)
        assert result == mock_scrape_response.text

        expected_payload = {
            "url": "https://example.com",
            "includeMarkdown": True,
            "tbs": "qdr:d",
            "gl": "us",
            "hl": "en",
        }
        call_args = mock_req.call_args
        assert json.loads(call_args[1]["data"]) == expected_payload


def test_scrape_webpage_exception(api_tools):
    """If requests.request raises during scraping, should catch and return error."""
    with patch("requests.request", side_effect=Exception("Scraping failed")):
        result = api_tools.scrape_webpage("https://example.com")
        result_json = json.loads(result)
        assert "error" in result_json
        assert "Scraping failed" in result_json["error"]


# Edge Cases and Integration Tests
def test_tools_without_optional_params():
    """Test initialization and usage with minimal parameters."""
    tools = SerperTools(api_key="test_key")
    assert tools.location == "us"
    assert tools.language == "en"
    assert tools.num_results == 10
    assert tools.date_range is None


def test_http_error_handling(api_tools):
    """Test that HTTP errors are properly handled."""
    mock_response = Mock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")

    with patch("requests.request", return_value=mock_response):
        result = api_tools.search_web("test query")
        result_json = json.loads(result)
        assert "error" in result_json
        assert "404 Not Found" in result_json["error"]
