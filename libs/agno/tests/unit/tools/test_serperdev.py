import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.serperapi import SerperApiTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure SERPER_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("SERPER_API_KEY", raising=False)


@pytest.fixture
def api_tools():
    """SerperApiTools with a known API key, custom location, and fewer results for testing."""
    return SerperApiTools(api_key="test_key", location="us", num_results=5)


@pytest.fixture
def mock_search_response():
    """Mock a successful Serper API HTTP response."""
    mock = Mock(spec=requests.Response)
    mock.text = '{"results": [{"title": "Test Result", "link": "http://example.com"}]}'
    return mock


def test_init_without_api_key_and_env(monkeypatch):
    """If no api_key argument and no SERPER_API_KEY in env, api_key should be None."""
    # Ensure environment has no key
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    tools = SerperApiTools()
    assert tools.api_key is None


def test_init_with_env_var(monkeypatch):
    """If SERPER_API_KEY is set in the environment, it is picked up."""
    monkeypatch.setenv("SERPER_API_KEY", "env_key")
    tools = SerperApiTools(api_key=None)
    assert tools.api_key == "env_key"


def test_search_google_no_api_key():
    """Calling search_google without any API key returns an error message."""
    tools = SerperApiTools(api_key=None)
    assert tools.search_google("anything") == "Please provide an API key"


def test_search_google_empty_query(api_tools):
    """Calling search_google with an empty query returns an error message."""
    assert api_tools.search_google("") == "Please provide a query to search for"


def test_search_google_success_default_location(api_tools, mock_search_response):
    """A successful search should return the raw response.text and call requests.request correctly."""
    with patch("requests.request", return_value=mock_search_response) as mock_req:
        result = api_tools.search_google("pytest testing")
        assert result == mock_search_response.text

        mock_req.assert_called_once_with(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps({"q": "pytest testing", "num": 5, "gl": "us"}),
        )


def test_search_google_success_override_location(api_tools, mock_search_response):
    """Overriding the location parameter should be respected in the request payload."""
    with patch("requests.request", return_value=mock_search_response) as mock_req:
        result = api_tools.search_google("pytest testing", location="uk")
        assert result == mock_search_response.text

        mock_req.assert_called_once_with(
            "POST",
            "https://google.serper.dev/search",
            headers={"X-API-KEY": "test_key", "Content-Type": "application/json"},
            data=json.dumps({"q": "pytest testing", "num": 5, "gl": "uk"}),
        )


def test_search_google_exception(api_tools):
    """If requests.request raises, search_google should catch and return an error string."""
    with patch("requests.request", side_effect=Exception("Network failure")):
        result = api_tools.search_google("failure test")
        assert "Error searching for the query failure test: Network failure" in result
