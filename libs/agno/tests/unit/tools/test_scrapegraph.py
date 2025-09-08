"""Unit tests for ScrapeGraphTools class."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.tools.scrapegraph import ScrapeGraphTools


@pytest.fixture
def mock_scrapegraph_modules():
    """Mock all scrapegraph module imports."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client,
        patch("agno.tools.scrapegraph.sgai_logger") as mock_logger,
    ):
        yield {
            "client": mock_client,
            "logger": mock_logger,
        }


@pytest.fixture
def mock_scrapegraph_client():
    """Create a mock ScrapeGraph client."""
    mock_client = Mock()
    mock_client.smartscraper.return_value = {
        "result": "<html><body>Test Content</body></html>",
        "request_id": "req_123456789",
        "status": "success",
    }
    return mock_client


@pytest.fixture
def scrapegraph_tools(mock_scrapegraph_modules, mock_scrapegraph_client):
    """Create a ScrapeGraphTools instance with mocked dependencies."""
    mock_scrapegraph_modules["client"].return_value = mock_scrapegraph_client
    
    with patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}):
        tools = ScrapeGraphTools(scrape=True, smartscraper=False)
        tools.client = mock_scrapegraph_client
        return tools


@pytest.fixture
def scrapegraph_tools_all_methods(mock_scrapegraph_modules, mock_scrapegraph_client):
    """Create a ScrapeGraphTools instance with all methods enabled."""
    mock_scrapegraph_modules["client"].return_value = mock_scrapegraph_client
    
    with patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}):
        tools = ScrapeGraphTools(
            smartscraper=True,
            markdownify=True,
            crawl=True,
            searchscraper=True,
            agentic_crawler=True,
            scrape=True,
        )
        tools.client = mock_scrapegraph_client
        return tools


class TestScrapeGraphToolsInitialization:
    """Test initialization and configuration of ScrapeGraphTools."""

    def test_init_with_api_key(self, mock_scrapegraph_modules):
        """Test initialization with API key."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        tools = ScrapeGraphTools(api_key="test_key")
        assert tools.api_key == "test_key"
        mock_scrapegraph_modules["client"].assert_called_once_with(api_key="test_key")

    def test_init_with_env_api_key(self, mock_scrapegraph_modules):
        """Test initialization with API key from environment."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "env_api_key"}):
            tools = ScrapeGraphTools()
            assert tools.api_key == "env_api_key"
            mock_scrapegraph_modules["client"].assert_called_once_with(api_key="env_api_key")

    def test_init_default_configuration(self, mock_scrapegraph_modules):
        """Test initialization with default configuration."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
            tools = ScrapeGraphTools()
            
            # Check that smartscraper is enabled by default
            tool_names = [func.name for func in tools.functions.values()]
            assert "smartscraper" in tool_names
            assert "scrape" not in tool_names  # scrape is disabled by default

    def test_init_with_scrape_enabled(self, mock_scrapegraph_modules):
        """Test initialization with scrape method enabled."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
            tools = ScrapeGraphTools(scrape=True, smartscraper=False)
            
            tool_names = [func.name for func in tools.functions.values()]
            assert "scrape" in tool_names
            assert "smartscraper" not in tool_names

    def test_init_markdownify_when_smartscraper_disabled(self, mock_scrapegraph_modules):
        """Test that markdownify is enabled when smartscraper is disabled."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
            tools = ScrapeGraphTools(smartscraper=False)
            
            tool_names = [func.name for func in tools.functions.values()]
            assert "markdownify" in tool_names
            assert "smartscraper" not in tool_names

    def test_init_all_methods_enabled(self, mock_scrapegraph_modules):
        """Test initialization with all methods enabled."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
            tools = ScrapeGraphTools(
                smartscraper=True,
                markdownify=True,
                crawl=True,
                searchscraper=True,
                agentic_crawler=True,
                scrape=True,
            )
            
            tool_names = [func.name for func in tools.functions.values()]
            expected_tools = [
                "smartscraper",
                "markdownify", 
                "crawl",
                "searchscraper",
                "agentic_crawler",
                "scrape",
            ]
            
            for tool_name in expected_tools:
                assert tool_name in tool_names, f"Tool {tool_name} should be registered"

    def test_toolkit_name(self, mock_scrapegraph_modules):
        """Test that toolkit has correct name."""
        mock_scrapegraph_modules["client"].return_value = Mock()
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}):
            tools = ScrapeGraphTools()
            assert tools.name == "scrapegraph_tools"


class TestScrapeMethod:
    """Test cases for the scrape method."""

    def test_scrape_success(self, scrapegraph_tools):
        """Test successful HTML scraping."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Test Content</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": expected_html,
            "request_id": "req_123456789",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url)

        # Assert
        scrapegraph_tools.client.smartscraper.assert_called_once_with(
            website_url=test_url,
            user_prompt="Extract the complete raw HTML content of the entire webpage, including all tags, attributes, and structure. Return the full HTML source code.",
            render_heavy_js=False,
            headers=None,
        )

        result_data = json.loads(result)
        assert result_data["html"] == expected_html
        assert result_data["scrape_request_id"] == "req_123456789"
        assert result_data["status"] == "success"
        assert result_data["url"] == test_url
        assert result_data["render_heavy_js"] is False
        assert result_data["headers"] is None
        assert result_data["error"] is None

    def test_scrape_with_js_rendering(self, scrapegraph_tools):
        """Test scraping with JavaScript rendering enabled."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>JS Rendered Content</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": expected_html,
            "request_id": "req_js_123",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(
            website_url=test_url,
            render_heavy_js=True
        )

        # Assert
        scrapegraph_tools.client.smartscraper.assert_called_once_with(
            website_url=test_url,
            user_prompt="Extract the complete raw HTML content of the entire webpage, including all tags, attributes, and structure. Return the full HTML source code.",
            render_heavy_js=True,
            headers=None,
        )

        result_data = json.loads(result)
        assert result_data["html"] == expected_html
        assert result_data["render_heavy_js"] is True

    def test_scrape_with_custom_headers(self, scrapegraph_tools):
        """Test scraping with custom headers."""
        # Arrange
        test_url = "https://example.com"
        custom_headers = {"User-Agent": "Custom Bot", "Accept": "text/html"}
        expected_html = "<html><body>Custom Headers Content</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": expected_html,
            "request_id": "req_headers_123",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(
            website_url=test_url,
            headers=custom_headers
        )

        # Assert
        scrapegraph_tools.client.smartscraper.assert_called_once_with(
            website_url=test_url,
            user_prompt="Extract the complete raw HTML content of the entire webpage, including all tags, attributes, and structure. Return the full HTML source code.",
            render_heavy_js=False,
            headers=custom_headers,
        )

        result_data = json.loads(result)
        assert result_data["headers"] == custom_headers

    def test_scrape_empty_url(self, scrapegraph_tools):
        """Test scraping with empty URL."""
        # Act
        result = scrapegraph_tools.scrape(website_url="")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "URL cannot be empty" in result_data["error"]

    def test_scrape_invalid_url(self, scrapegraph_tools):
        """Test scraping with invalid URL format."""
        # Act
        result = scrapegraph_tools.scrape(website_url="not-a-url")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "Invalid URL" in result_data["error"]

    def test_scrape_url_without_protocol(self, scrapegraph_tools):
        """Test scraping with URL missing protocol."""
        # Act
        result = scrapegraph_tools.scrape(website_url="example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "Invalid URL" in result_data["error"]

    def test_scrape_api_error(self, scrapegraph_tools):
        """Test scraping when API returns an error."""
        # Arrange
        scrapegraph_tools.client.smartscraper.side_effect = Exception("API Error")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "API Error"
        assert result_data["html"] == ""

    def test_scrape_result_with_html_field(self, scrapegraph_tools):
        """Test scraping when result contains HTML in 'html' field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>HTML Field Content</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": {"html": expected_html},
            "request_id": "req_html_field",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_result_with_content_field(self, scrapegraph_tools):
        """Test scraping when result contains HTML in 'content' field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Content Field Content</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": {"content": expected_html},
            "request_id": "req_content_field",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_result_direct_html_field(self, scrapegraph_tools):
        """Test scraping when response has direct 'html' field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Direct HTML Field</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "html": expected_html,
            "request_id": "req_direct_html",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_result_direct_content_field(self, scrapegraph_tools):
        """Test scraping when response has direct 'content' field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Direct Content Field</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "content": expected_html,
            "request_id": "req_direct_content",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_no_html_content(self, scrapegraph_tools):
        """Test scraping when no HTML content is returned."""
        # Arrange
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": "No HTML here",
            "request_id": "req_no_html",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == ""


class TestScrapeMethodIntegration:
    """Integration tests for the scrape method."""

    def test_scrape_with_all_parameters(self, scrapegraph_tools):
        """Test scraping with all parameters provided."""
        # Arrange
        test_url = "https://example.com"
        custom_headers = {"User-Agent": "Test Bot", "Accept-Language": "en-US"}
        expected_html = "<html><body>Full Test</body></html>"
        
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": expected_html,
            "request_id": "req_full_test",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(
            website_url=test_url,
            render_heavy_js=True,
            headers=custom_headers
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html
        assert result_data["url"] == test_url
        assert result_data["render_heavy_js"] is True
        assert result_data["headers"] == custom_headers
        assert result_data["status"] == "success"

    def test_scrape_response_structure(self, scrapegraph_tools):
        """Test that scrape response has correct structure."""
        # Arrange
        scrapegraph_tools.client.smartscraper.return_value = {
            "result": "<html><body>Test</body></html>",
            "request_id": "req_structure_test",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        
        # Check all required fields are present
        required_fields = [
            "html", "scrape_request_id", "status", "error", 
            "url", "render_heavy_js", "headers"
        ]
        for field in required_fields:
            assert field in result_data, f"Field {field} should be present in response"

        # Check field types
        assert isinstance(result_data["html"], str)
        assert isinstance(result_data["scrape_request_id"], str)
        assert isinstance(result_data["status"], str)
        assert isinstance(result_data["url"], str)
        assert isinstance(result_data["render_heavy_js"], bool)
        assert result_data["headers"] is None or isinstance(result_data["headers"], dict)


class TestScrapeMethodErrorHandling:
    """Test error handling in the scrape method."""

    def test_scrape_network_error(self, scrapegraph_tools):
        """Test handling of network errors."""
        # Arrange
        scrapegraph_tools.client.smartscraper.side_effect = ConnectionError("Network error")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "Network error" in result_data["error"]
        assert result_data["html"] == ""

    def test_scrape_timeout_error(self, scrapegraph_tools):
        """Test handling of timeout errors."""
        # Arrange
        scrapegraph_tools.client.smartscraper.side_effect = TimeoutError("Request timeout")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "Request timeout" in result_data["error"]

    def test_scrape_json_decode_error(self, scrapegraph_tools):
        """Test handling of JSON decode errors."""
        # Arrange
        scrapegraph_tools.client.smartscraper.return_value = "Invalid JSON response"

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] is not None


if __name__ == "__main__":
    pytest.main([__file__])
