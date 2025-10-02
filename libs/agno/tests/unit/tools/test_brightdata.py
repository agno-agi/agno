"""Unit tests for BrightDataTools class."""

import base64
import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.agent import Agent
from agno.media import Image
from agno.tools.brightdata import BrightDataTools
from agno.tools.function import ToolResult


@pytest.fixture
def mock_agent():
    """Create a mock Agent instance."""
    agent = Mock(spec=Agent)
    return agent


@pytest.fixture
def mock_requests():
    """Mock requests module."""
    with patch("agno.tools.brightdata.requests") as mock_requests:
        yield mock_requests


@pytest.fixture
def brightdata_tools():
    """Create BrightDataTools instance with test API key."""
    return BrightDataTools(
        api_key="test_api_key",
        serp_zone="test_serp_zone",
        web_unlocker_zone="test_web_unlocker_zone",
        enable_scrape_markdown=True,
        enable_screenshot=True,
        enable_search_engine=True,
        enable_web_data_feed=True,
        verbose=True,
    )


def test_init_with_api_key():
    """Test initialization with provided API key."""
    tools = BrightDataTools(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.web_unlocker_zone == "web_unlocker1"
    assert tools.serp_zone == "serp_api"


def test_init_with_env_var():
    """Test initialization with environment variable."""
    with patch.dict("os.environ", {"BRIGHT_DATA_API_KEY": "env_key"}):
        tools = BrightDataTools()
        assert tools.api_key == "env_key"


def test_init_without_api_key():
    """Test initialization without API key raises ValueError."""
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ValueError, match="No Bright Data API key provided"):
            BrightDataTools(api_key=None)


def test_init_with_selective_tools():
    """Test initialization with only selected tools."""
    tools = BrightDataTools(
        api_key="test_key",
        enable_scrape_markdown=True,
        enable_screenshot=False,
        enable_search_engine=True,
        enable_web_data_feed=False,
    )

    function_names = [func.name for func in tools.functions.values()]
    assert "scrape_as_markdown" in function_names
    assert "get_screenshot" not in function_names
    assert "search_engine" in function_names
    assert "web_data_feed" not in function_names


def test_make_request_success(brightdata_tools, mock_requests):
    """Test successful _make_request."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "Success response"
    mock_requests.post.return_value = mock_response

    payload = {"url": "https://example.com", "zone": "test_zone"}
    result = brightdata_tools._make_request(payload)

    assert result == "Success response"
    mock_requests.post.assert_called_once_with(
        brightdata_tools.endpoint, headers=brightdata_tools.headers, data=json.dumps(payload)
    )


def test_make_request_failure(brightdata_tools, mock_requests):
    """Test _make_request with HTTP error."""
    mock_response = Mock()
    mock_response.status_code = 400
    mock_response.text = "Bad Request"
    mock_requests.post.return_value = mock_response

    payload = {"url": "https://example.com"}

    with pytest.raises(Exception, match="Failed to scrape: 400 - Bad Request"):
        brightdata_tools._make_request(payload)


def test_make_request_exception(brightdata_tools, mock_requests):
    """Test _make_request with network exception."""
    mock_requests.post.side_effect = requests.RequestException("Network error")

    payload = {"url": "https://example.com"}

    with pytest.raises(Exception, match="Request failed: Network error"):
        brightdata_tools._make_request(payload)


def test_scrape_as_markdown_success(brightdata_tools, mock_requests):
    """Test successful scrape_as_markdown."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "# Markdown Content\n\nThis is a test."
    mock_requests.post.return_value = mock_response

    result = brightdata_tools.scrape_as_markdown("https://example.com")

    assert result == "# Markdown Content\n\nThis is a test."
    mock_requests.post.assert_called_once()
    args, kwargs = mock_requests.post.call_args
    payload = json.loads(kwargs["data"])
    assert payload["url"] == "https://example.com"
    assert payload["data_format"] == "markdown"
    assert payload["zone"] == "test_web_unlocker_zone"


def test_scrape_as_markdown_no_api_key():
    """Test scrape_as_markdown without API key."""
    with patch.dict("os.environ", {}, clear=True):
        tools = BrightDataTools(api_key="test_key")  # Create with key first
        tools.api_key = None  # Then remove it to test the method behavior

        result = tools.scrape_as_markdown("https://example.com")
        assert result == "Please provide a Bright Data API key"


def test_scrape_as_markdown_no_url(brightdata_tools):
    """Test scrape_as_markdown without URL."""
    result = brightdata_tools.scrape_as_markdown("")
    assert result == "Please provide a URL to scrape"


def test_scrape_as_markdown_exception(brightdata_tools, mock_requests):
    """Test scrape_as_markdown with exception."""
    mock_requests.post.side_effect = Exception("Network error")

    result = brightdata_tools.scrape_as_markdown("https://example.com")
    assert "Error scraping URL https://example.com: Request failed: Network error" in result


def test_get_screenshot_success(brightdata_tools, mock_requests, mock_agent):
    """Test successful get_screenshot."""
    # Mock image bytes
    mock_image_bytes = b"fake_png_data"
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.content = mock_image_bytes
    mock_requests.post.return_value = mock_response

    with patch("agno.tools.brightdata.uuid4") as mock_uuid:
        mock_uuid.return_value = Mock()
        mock_uuid.return_value.__str__ = Mock(return_value="test-uuid-123")

        result = brightdata_tools.get_screenshot(mock_agent, "https://example.com")

    # Check that result is a ToolResult with success content
    assert isinstance(result, ToolResult)
    assert "Screenshot captured and added as artifact with ID: test-uuid-123" in result.content
    assert result.images is not None
    assert len(result.images) == 1

    # Verify API call
    mock_requests.post.assert_called_once()
    args, kwargs = mock_requests.post.call_args
    payload = json.loads(kwargs["data"])
    assert payload["url"] == "https://example.com"
    assert payload["data_format"] == "screenshot"
    assert payload["zone"] == "test_web_unlocker_zone"

    # Verify ImageArtifact creation
    image_artifact = result.images[0]
    assert isinstance(image_artifact, Image)
    assert image_artifact.id == "test-uuid-123"
    assert image_artifact.mime_type == "image/png"
    assert image_artifact.original_prompt == "Screenshot of https://example.com"

    # Verify base64 encoding
    expected_base64 = base64.b64encode(mock_image_bytes).decode("utf-8")
    assert image_artifact.content == expected_base64.encode("utf-8")


def test_get_screenshot_no_api_key(mock_agent):
    """Test get_screenshot without API key."""
    with patch.dict("os.environ", {}, clear=True):
        tools = BrightDataTools(api_key="test_key")  # Create with key first
        tools.api_key = None  # Then remove it to test the method behavior

        result = tools.get_screenshot(mock_agent, "https://example.com")

        # Check that result is a ToolResult with error content
        assert isinstance(result, ToolResult)
        assert result.content == "Please provide a Bright Data API key"
        assert result.images is None


def test_get_screenshot_no_url(brightdata_tools, mock_agent):
    """Test get_screenshot without URL."""
    result = brightdata_tools.get_screenshot(mock_agent, "")

    # Check that result is a ToolResult with error content
    assert isinstance(result, ToolResult)
    assert result.content == "Please provide a URL to screenshot"
    assert result.images is None


def test_get_screenshot_http_error(brightdata_tools, mock_requests, mock_agent):
    """Test get_screenshot with HTTP error."""
    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_requests.post.return_value = mock_response

    result = brightdata_tools.get_screenshot(mock_agent, "https://example.com")

    # Check that result is a ToolResult with error content
    assert isinstance(result, ToolResult)
    assert "Error taking screenshot of https://example.com: Error 500: Internal Server Error" in result.content
    assert result.images is None


def test_search_engine_success(brightdata_tools, mock_requests):
    """Test successful search_engine."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "Search results markdown content"
    mock_requests.post.return_value = mock_response

    result = brightdata_tools.search_engine("python web scraping", engine="google", num_results=5)

    assert result == "Search results markdown content"
    mock_requests.post.assert_called_once()
    args, kwargs = mock_requests.post.call_args
    payload = json.loads(kwargs["data"])
    assert "python%20web%20scraping" in payload["url"]
    assert payload["data_format"] == "markdown"
    assert payload["zone"] == "test_serp_zone"


def test_search_engine_with_params(brightdata_tools, mock_requests):
    """Test search_engine with language and country parameters."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "Localized search results"
    mock_requests.post.return_value = mock_response

    brightdata_tools.search_engine("test query", engine="google", num_results=10, language="en", country_code="US")

    mock_requests.post.assert_called_once()
    args, kwargs = mock_requests.post.call_args
    payload = json.loads(kwargs["data"])
    assert "hl=en" in payload["url"]
    assert "gl=US" in payload["url"]
    assert "num=10" in payload["url"]


def test_search_engine_bing(brightdata_tools, mock_requests):
    """Test search_engine with Bing."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.text = "Bing search results"
    mock_requests.post.return_value = mock_response

    brightdata_tools.search_engine("test query", engine="bing")

    mock_requests.post.assert_called_once()
    args, kwargs = mock_requests.post.call_args
    payload = json.loads(kwargs["data"])
    assert "bing.com/search" in payload["url"]


def test_search_engine_invalid_engine(brightdata_tools):
    """Test search_engine with invalid engine."""
    result = brightdata_tools.search_engine("test query", engine="invalid")
    assert "Unsupported search engine: invalid" in result


def test_search_engine_no_api_key():
    """Test search_engine without API key."""
    with patch.dict("os.environ", {}, clear=True):
        tools = BrightDataTools(api_key="test_key")  # Create with key first
        tools.api_key = None  # Then remove it to test the method behavior

        result = tools.search_engine("test query")
        assert result == "Please provide a Bright Data API key"


def test_search_engine_no_query(brightdata_tools):
    """Test search_engine without query."""
    result = brightdata_tools.search_engine("")
    assert result == "Please provide a query to search for"


def test_web_data_feed_success(brightdata_tools, mock_requests):
    """Test successful web_data_feed."""
    # Mock trigger response
    mock_trigger_response = Mock()
    mock_trigger_response.json.return_value = {"snapshot_id": "test_snapshot_123"}

    # Mock snapshot response
    mock_snapshot_response = Mock()
    mock_snapshot_response.json.return_value = {
        "product_title": "Test Product",
        "price": "$29.99",
        "description": "Test product description",
    }

    mock_requests.post.side_effect = [mock_trigger_response]
    mock_requests.get.return_value = mock_snapshot_response

    result = brightdata_tools.web_data_feed("amazon_product", "https://amazon.com/dp/B123")

    # Should return JSON string
    result_data = json.loads(result)
    assert result_data["product_title"] == "Test Product"
    assert result_data["price"] == "$29.99"

    # Verify trigger call
    assert mock_requests.post.called
    trigger_args = mock_requests.post.call_args
    assert "datasets/v3/trigger" in trigger_args[0][0]
    assert trigger_args[1]["json"] == [{"url": "https://amazon.com/dp/B123"}]

    # Verify snapshot call
    assert mock_requests.get.called
    snapshot_args = mock_requests.get.call_args
    assert "snapshot/test_snapshot_123" in snapshot_args[0][0]


def test_web_data_feed_invalid_source(brightdata_tools):
    """Test web_data_feed with invalid source type."""
    result = brightdata_tools.web_data_feed("invalid_source", "https://example.com")
    assert "Invalid source_type: invalid_source" in result


def test_web_data_feed_no_api_key():
    """Test web_data_feed without API key."""
    with patch.dict("os.environ", {}, clear=True):
        tools = BrightDataTools(api_key="test_key")  # Create with key first
        tools.api_key = None  # Then remove it to test the method behavior

        result = tools.web_data_feed("amazon_product", "https://example.com")
        assert result == "Please provide a Bright Data API key"


def test_web_data_feed_no_url(brightdata_tools):
    """Test web_data_feed without URL."""
    result = brightdata_tools.web_data_feed("amazon_product", "")
    assert result == "Please provide a URL to retrieve data from"


def test_web_data_feed_no_snapshot_id(brightdata_tools, mock_requests):
    """Test web_data_feed when no snapshot ID is returned."""
    mock_trigger_response = Mock()
    mock_trigger_response.json.return_value = {}  # No snapshot_id
    mock_requests.post.return_value = mock_trigger_response

    result = brightdata_tools.web_data_feed("amazon_product", "https://amazon.com/dp/B123")
    assert result == "No snapshot ID returned from trigger request"


def test_web_data_feed_with_reviews_param(brightdata_tools, mock_requests):
    """Test web_data_feed with num_of_reviews parameter."""
    mock_trigger_response = Mock()
    mock_trigger_response.json.return_value = {"snapshot_id": "test_snapshot_123"}

    mock_snapshot_response = Mock()
    mock_snapshot_response.json.return_value = {"reviews": ["review1", "review2"]}

    mock_requests.post.side_effect = [mock_trigger_response]
    mock_requests.get.return_value = mock_snapshot_response

    brightdata_tools.web_data_feed("facebook_company_reviews", "https://facebook.com/company", num_of_reviews=50)

    # Verify the request included num_of_reviews
    trigger_args = mock_requests.post.call_args
    assert trigger_args[1]["json"] == [{"url": "https://facebook.com/company", "num_of_reviews": "50"}]


def test_web_data_feed_exception(brightdata_tools, mock_requests):
    """Test web_data_feed with exception."""
    mock_requests.post.side_effect = Exception("Network error")

    result = brightdata_tools.web_data_feed("amazon_product", "https://amazon.com/dp/B123")
    assert "Error retrieving amazon_product data from https://amazon.com/dp/B123: Network error" in result
