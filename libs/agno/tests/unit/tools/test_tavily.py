"""Unit tests for TavilyTools class."""

import os
from unittest.mock import Mock, patch

import pytest
from tavily import TavilyClient  # noqa

from agno.tools.tavily import TavilyTools

TEST_API_KEY = os.environ.get("TAVILY_API_KEY", "test_api_key")
TEST_API_BASE_URL = os.environ.get("TAVILY_API_BASE_URL", "https://custom.tavily.com")


@pytest.fixture
def mock_tavily_client():
    """Create a mock TavilyClient instance."""
    with patch("agno.tools.tavily.TavilyClient") as mock_client_cls:
        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def tavily_tools(mock_tavily_client):
    """Create a TavilyTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"TAVILY_API_KEY": TEST_API_KEY}):
        tools = TavilyTools()
        tools.client = mock_tavily_client
        return tools


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.tavily.TavilyClient"):
        with patch.dict(
            "os.environ", {"TAVILY_API_KEY": TEST_API_KEY, "TAVILY_API_BASE_URL": TEST_API_BASE_URL}, clear=True
        ):
            tools = TavilyTools()
            assert tools.api_key == TEST_API_KEY
            assert tools.api_base_url == TEST_API_BASE_URL
            assert tools.search_depth == "advanced"
            assert tools.extract_depth == "basic"
            assert tools.extract_format == "markdown"
            assert tools.client is not None


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.tavily.TavilyClient"):
        tools = TavilyTools(
            api_key="param_api_key",
            api_base_url="https://custom.tavily.com",
            search_depth="basic",
            extract_depth="advanced",
            extract_format="text",
            include_images=True,
            include_favicon=True,
        )
        assert tools.api_key == "param_api_key"
        assert tools.api_base_url == "https://custom.tavily.com"
        assert tools.search_depth == "basic"
        assert tools.extract_depth == "advanced"
        assert tools.extract_format == "text"
        assert tools.include_images is True
        assert tools.include_favicon is True


def test_init_with_all_flag():
    """Test initialization with all=True flag."""
    with patch("agno.tools.tavily.TavilyClient"):
        tools = TavilyTools(all=True)
        # Check that tools list includes both search and extract
        tool_names = [tool.__name__ for tool in tools.tools]
        assert "web_search_using_tavily" in tool_names or "web_search_with_tavily" in tool_names
        assert "extract_url_content" in tool_names


# ============================================================================
# SEARCH TESTS (Existing Functionality)
# ============================================================================


def test_web_search_using_tavily(tavily_tools, mock_tavily_client):
    """Test web_search_using_tavily method."""
    # Setup mock response
    mock_response = {
        "query": "test query",
        "answer": "Test answer",
        "results": [
            {"title": "Result 1", "url": "https://example1.com", "content": "Content 1", "score": 0.9},
            {"title": "Result 2", "url": "https://example2.com", "content": "Content 2", "score": 0.8},
        ],
    }
    mock_tavily_client.search.return_value = mock_response

    # Call the method
    result = tavily_tools.web_search_using_tavily("test query")

    # Verify the response format is correct
    assert "test query" in result or "Result 1" in result
    mock_tavily_client.search.assert_called_once()


# ============================================================================
# EXTRACT TESTS (New Functionality)
# ============================================================================


def test_extract_single_url_markdown(tavily_tools, mock_tavily_client):
    """Test extract_url_content with single URL in markdown format."""
    # Setup mock response
    mock_response = {
        "results": [
            {
                "url": "https://example.com",
                "raw_content": "# Test Page\n\nThis is test content.",
            }
        ]
    }
    mock_tavily_client.extract.return_value = mock_response

    # Set format to markdown
    tavily_tools.extract_format = "markdown"

    # Call the method
    result = tavily_tools.extract_url_content("https://example.com")

    # Verify results
    assert "https://example.com" in result
    assert "# Test Page" in result
    assert "This is test content" in result
    mock_tavily_client.extract.assert_called_once()
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args["urls"] == ["https://example.com"]
    assert call_args["depth"] == "basic"


def test_extract_single_url_text(tavily_tools, mock_tavily_client):
    """Test extract_url_content with single URL in text format."""
    # Setup mock response
    mock_response = {
        "results": [
            {
                "url": "https://example.com",
                "raw_content": "Plain text content without markdown.",
            }
        ]
    }
    mock_tavily_client.extract.return_value = mock_response

    # Set format to text
    tavily_tools.extract_format = "text"

    # Call the method
    result = tavily_tools.extract_url_content("https://example.com")

    # Verify results
    assert "URL: https://example.com" in result
    assert "Plain text content" in result
    assert "-" * 80 in result  # Text format includes separator
    mock_tavily_client.extract.assert_called_once()


def test_extract_multiple_urls(tavily_tools, mock_tavily_client):
    """Test extract_url_content with multiple comma-separated URLs."""
    # Setup mock response
    mock_response = {
        "results": [
            {"url": "https://example1.com", "raw_content": "# Page 1\n\nContent from page 1."},
            {"url": "https://example2.com", "raw_content": "# Page 2\n\nContent from page 2."},
        ]
    }
    mock_tavily_client.extract.return_value = mock_response

    # Call the method with comma-separated URLs
    result = tavily_tools.extract_url_content("https://example1.com,https://example2.com")

    # Verify results
    assert "https://example1.com" in result
    assert "https://example2.com" in result
    assert "Page 1" in result
    assert "Page 2" in result
    mock_tavily_client.extract.assert_called_once()
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args["urls"] == ["https://example1.com", "https://example2.com"]


def test_extract_with_advanced_depth(tavily_tools, mock_tavily_client):
    """Test extract_url_content with advanced depth."""
    # Setup mock response
    mock_response = {"results": [{"url": "https://example.com", "raw_content": "Advanced content."}]}
    mock_tavily_client.extract.return_value = mock_response

    # Set advanced depth
    tavily_tools.extract_depth = "advanced"

    # Call the method
    tavily_tools.extract_url_content("https://example.com")

    # Verify advanced depth was used
    mock_tavily_client.extract.assert_called_once()
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args["depth"] == "advanced"


def test_extract_with_images(tavily_tools, mock_tavily_client):
    """Test extract_url_content with include_images parameter."""
    # Setup mock response
    mock_response = {"results": [{"url": "https://example.com", "raw_content": "Content with images."}]}
    mock_tavily_client.extract.return_value = mock_response

    # Enable images
    tavily_tools.include_images = True

    # Call the method
    tavily_tools.extract_url_content("https://example.com")

    # Verify include_images was passed
    mock_tavily_client.extract.assert_called_once()
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args.get("include_images") is True


def test_extract_with_favicon(tavily_tools, mock_tavily_client):
    """Test extract_url_content with include_favicon parameter."""
    # Setup mock response
    mock_response = {"results": [{"url": "https://example.com", "raw_content": "Content with favicon."}]}
    mock_tavily_client.extract.return_value = mock_response

    # Enable favicon
    tavily_tools.include_favicon = True

    # Call the method
    tavily_tools.extract_url_content("https://example.com")

    # Verify include_favicon was passed
    mock_tavily_client.extract.assert_called_once()
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args.get("include_favicon") is True


def test_extract_with_timeout(tavily_tools, mock_tavily_client):
    """Test extract_url_content with custom timeout."""
    # Setup mock response
    mock_response = {"results": [{"url": "https://example.com", "raw_content": "Content."}]}
    mock_tavily_client.extract.return_value = mock_response

    # Set custom timeout
    tavily_tools.extract_timeout = 30

    # Call the method
    tavily_tools.extract_url_content("https://example.com")

    # Verify timeout was passed
    mock_tavily_client.extract.assert_called_once()
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args.get("timeout") == 30


def test_extract_failed_extraction(tavily_tools, mock_tavily_client):
    """Test extract_url_content with failed extraction."""
    # Setup mock response with failed extraction
    mock_response = {
        "results": [
            {
                "url": "https://example.com",
                "failed_reason": "Page not found",
            }
        ]
    }
    mock_tavily_client.extract.return_value = mock_response

    tavily_tools.extract_format = "markdown"

    # Call the method
    result = tavily_tools.extract_url_content("https://example.com")

    # Verify failure is noted in output
    assert "https://example.com" in result
    assert "Extraction Failed" in result or "Page not found" in result


def test_extract_empty_response(tavily_tools, mock_tavily_client):
    """Test extract_url_content with empty response."""
    # Setup mock response with no results
    mock_response = {"results": []}
    mock_tavily_client.extract.return_value = mock_response

    # Call the method
    result = tavily_tools.extract_url_content("https://example.com")

    # Verify error message
    assert "Error" in result or "No content" in result


def test_extract_no_results_key(tavily_tools, mock_tavily_client):
    """Test extract_url_content with missing results key."""
    # Setup mock response without results key
    mock_response = {}
    mock_tavily_client.extract.return_value = mock_response

    # Call the method
    result = tavily_tools.extract_url_content("https://example.com")

    # Verify error message
    assert "Error" in result


def test_extract_invalid_url(tavily_tools, mock_tavily_client):
    """Test extract_url_content with empty/invalid URL."""
    # Call the method with empty string
    result = tavily_tools.extract_url_content("")

    # Verify error message
    assert "Error" in result or "No valid URLs" in result
    mock_tavily_client.extract.assert_not_called()


def test_extract_exception_handling(tavily_tools, mock_tavily_client):
    """Test extract_url_content with exception during extraction."""
    # Setup mock to raise exception
    mock_tavily_client.extract.side_effect = Exception("API Error")

    # Call the method
    result = tavily_tools.extract_url_content("https://example.com")

    # Verify error is handled gracefully
    assert "Error" in result
    assert "API Error" in result


def test_extract_whitespace_handling(tavily_tools, mock_tavily_client):
    """Test extract_url_content handles whitespace in URLs."""
    # Setup mock response
    mock_response = {
        "results": [
            {"url": "https://example1.com", "raw_content": "Content 1"},
            {"url": "https://example2.com", "raw_content": "Content 2"},
        ]
    }
    mock_tavily_client.extract.return_value = mock_response

    # Call with URLs containing whitespace
    tavily_tools.extract_url_content("  https://example1.com  ,  https://example2.com  ")

    # Verify URLs were cleaned
    call_args = mock_tavily_client.extract.call_args[1]
    assert call_args["urls"] == ["https://example1.com", "https://example2.com"]


# ============================================================================
# FORMAT HELPER TESTS
# ============================================================================


def test_format_extract_markdown():
    """Test _format_extract_markdown helper method."""
    with patch("agno.tools.tavily.TavilyClient"):
        tools = TavilyTools()

        # Test with successful extraction
        results = [{"url": "https://example.com", "raw_content": "# Test\n\nContent here."}]
        output = tools._format_extract_markdown(results)

        assert "## https://example.com" in output
        assert "# Test" in output
        assert "Content here" in output


def test_format_extract_text():
    """Test _format_extract_text helper method."""
    with patch("agno.tools.tavily.TavilyClient"):
        tools = TavilyTools()

        # Test with successful extraction
        results = [{"url": "https://example.com", "raw_content": "Plain text content."}]
        output = tools._format_extract_text(results)

        assert "URL: https://example.com" in output
        assert "-" * 80 in output
        assert "Plain text content" in output
