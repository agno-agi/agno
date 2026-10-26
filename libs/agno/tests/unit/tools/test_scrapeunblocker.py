"""Unit tests for ScrapeUnblockerTools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.scrapeunblocker import ScrapeUnblockerTools


@pytest.fixture
def mock_response():
    response = MagicMock()
    response.text = "<html><head><title>Test Page</title></head><body>content</body></html>"
    response.json.return_value = {"title": "Test Page"}
    response.raise_for_status.return_value = None
    return response


def test_init_with_api_key():
    tools = ScrapeUnblockerTools(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.name == "scrapeunblocker_tools"


def test_init_from_env():
    with patch.dict("os.environ", {"SCRAPEUNBLOCKER_API_KEY": "env_key"}, clear=True):
        assert ScrapeUnblockerTools().api_key == "env_key"


def test_init_without_api_key_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError):
            ScrapeUnblockerTools()


def test_all_tools_registered_by_default():
    tools = ScrapeUnblockerTools(api_key="test_key")
    names = [f.name for f in tools.functions.values()]
    assert "scrape_website" in names
    assert "search_google" in names


def test_selective_tool_registration():
    tools = ScrapeUnblockerTools(api_key="test_key", enable_search_google=False)
    names = [f.name for f in tools.functions.values()]
    assert names == ["scrape_website"]


def test_all_flag_overrides_disabled_tools():
    tools = ScrapeUnblockerTools(
        api_key="test_key", enable_scrape_website=False, enable_search_google=False, all=True
    )
    names = [f.name for f in tools.functions.values()]
    assert "scrape_website" in names
    assert "search_google" in names


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_scrape_website(mock_post, mock_response):
    mock_post.return_value = mock_response
    tools = ScrapeUnblockerTools(api_key="test_key")

    result = tools.scrape_website("https://example.com")

    assert "Test Page" in result
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-ScrapeUnblocker-Key"] == "test_key"
    assert kwargs["params"]["url"] == "https://example.com"


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_scrape_website_omits_unset_params(mock_post, mock_response):
    mock_post.return_value = mock_response
    tools = ScrapeUnblockerTools(api_key="test_key")

    tools.scrape_website("https://example.com")

    _, kwargs = mock_post.call_args
    assert kwargs["params"] == {"url": "https://example.com"}


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_scrape_website_forwards_proxy_country(mock_post, mock_response):
    mock_post.return_value = mock_response
    tools = ScrapeUnblockerTools(api_key="test_key", proxy_country="de")

    tools.scrape_website("https://example.com")

    _, kwargs = mock_post.call_args
    assert kwargs["params"]["proxy_country"] == "de"


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_scrape_website_parsed_data(mock_post, mock_response):
    mock_post.return_value = mock_response
    tools = ScrapeUnblockerTools(api_key="test_key", parsed_data=True)

    result = tools.scrape_website("https://example.com")

    assert json.loads(result) == {"title": "Test Page"}
    _, kwargs = mock_post.call_args
    assert kwargs["params"]["parsed_data"] is True


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_scrape_website_truncates(mock_post, mock_response):
    mock_response.text = "x" * 5000
    mock_post.return_value = mock_response
    tools = ScrapeUnblockerTools(api_key="test_key", max_length=100)

    assert len(tools.scrape_website("https://example.com")) == 100


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_scrape_website_error_returns_message(mock_post):
    mock_post.side_effect = Exception("Connection refused")
    tools = ScrapeUnblockerTools(api_key="test_key")

    result = tools.scrape_website("https://example.com")

    assert "Error scraping" in result
    assert "Connection refused" in result


def test_scrape_website_requires_url():
    tools = ScrapeUnblockerTools(api_key="test_key")
    assert "url is required" in tools.scrape_website("")


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_search_google(mock_post, mock_response):
    mock_response.json.return_value = {"organic": [{"title": "Result"}]}
    mock_post.return_value = mock_response
    tools = ScrapeUnblockerTools(api_key="test_key")

    result = tools.search_google("running shoes")

    assert json.loads(result) == {"organic": [{"title": "Result"}]}
    _, kwargs = mock_post.call_args
    assert kwargs["params"]["keyword"] == "running shoes"
    assert kwargs["params"]["pages_to_check"] == 1


@patch("agno.tools.scrapeunblocker.httpx.post")
def test_search_google_error_returns_message(mock_post):
    mock_post.side_effect = Exception("Timeout")
    tools = ScrapeUnblockerTools(api_key="test_key")

    result = tools.search_google("running shoes")

    assert "Error searching" in result
    assert "Timeout" in result


def test_search_google_requires_keyword():
    tools = ScrapeUnblockerTools(api_key="test_key")
    assert "keyword is required" in tools.search_google("")
