"""Integration tests for ScrapeGraphTools scrape method."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools


@pytest.fixture
def mock_scrapegraph_client():
    """Create a mock ScrapeGraph client for integration tests."""
    mock_client = Mock()
    mock_client.smartscraper.return_value = {
        "result": "<html><head><title>Test Page</title></head><body><h1>Hello World</h1><p>This is a test page.</p></body></html>",
        "request_id": "req_integration_123",
        "status": "success",
    }
    return mock_client


@pytest.fixture
def scrapegraph_tools_integration(mock_scrapegraph_client):
    """Create ScrapeGraphTools instance for integration tests."""
    with patch("agno.tools.scrapegraph.Client") as mock_client_class:
        mock_client_class.return_value = mock_scrapegraph_client
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}):
            tools = ScrapeGraphTools(scrape=True, smartscraper=False)
            tools.client = mock_scrapegraph_client
            return tools


@pytest.fixture
def agent_with_scrape_tools(scrapegraph_tools_integration):
    """Create an agent with ScrapeGraphTools for integration tests."""
    return Agent(
        name="Scrape Test Agent",
        tools=[scrapegraph_tools_integration],
        instructions=[
            "You are a web scraping assistant.",
            "Use the scrape tool to get HTML content from websites.",
            "Always provide detailed analysis of the scraped content."
        ],
        show_tool_calls=True,
        markdown=True,
    )


class TestScrapeMethodIntegration:
    """Integration tests for the scrape method."""

    def test_scrape_tool_registration(self, scrapegraph_tools_integration):
        """Test that scrape tool is properly registered."""
        tool_names = [func.name for func in scrapegraph_tools_integration.functions.values()]
        assert "scrape" in tool_names

    def test_scrape_method_direct_call(self, scrapegraph_tools_integration):
        """Test direct call to scrape method."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Test Content</body></html>"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "result": expected_html,
            "request_id": "req_direct_123",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html
        assert result_data["status"] == "success"
        assert result_data["url"] == test_url

    def test_scrape_with_agent_basic(self, agent_with_scrape_tools):
        """Test scrape method through agent interaction."""
        # Arrange
        test_url = "https://example.com"
        
        # Act
        response = agent_with_scrape_tools.run(f"Use the scrape tool to get HTML content from {test_url}")

        # Assert
        assert response is not None
        # The response should contain information about the scraping operation
        assert hasattr(response, 'content') or hasattr(response, 'message')

    def test_scrape_with_agent_detailed_request(self, agent_with_scrape_tools):
        """Test scrape method with detailed agent request."""
        # Arrange
        test_url = "https://example.com"
        
        # Act
        response = agent_with_scrape_tools.run(
            f"Use the scrape tool to get the complete HTML content from {test_url}. "
            "Include information about the request ID and status."
        )

        # Assert
        assert response is not None
        # The agent should have used the scrape tool
        assert hasattr(response, 'content') or hasattr(response, 'message')

    def test_scrape_with_js_rendering_integration(self, scrapegraph_tools_integration):
        """Test scrape method with JavaScript rendering."""
        # Arrange
        test_url = "https://example.com"
        js_html = "<html><body><div id='js-content'>JS Rendered Content</div></body></html>"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "result": js_html,
            "request_id": "req_js_integration",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(
            website_url=test_url,
            render_heavy_js=True
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == js_html
        assert result_data["render_heavy_js"] is True
        
        # Verify the client was called with correct parameters
        scrapegraph_tools_integration.client.smartscraper.assert_called_once_with(
            website_url=test_url,
            user_prompt="Extract the complete raw HTML content of the entire webpage, including all tags, attributes, and structure. Return the full HTML source code.",
            render_heavy_js=True,
            headers=None,
        )

    def test_scrape_with_custom_headers_integration(self, scrapegraph_tools_integration):
        """Test scrape method with custom headers."""
        # Arrange
        test_url = "https://example.com"
        custom_headers = {
            "User-Agent": "Integration Test Bot",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "result": "<html><body>Headers Test</body></html>",
            "request_id": "req_headers_integration",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(
            website_url=test_url,
            headers=custom_headers
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["headers"] == custom_headers
        
        # Verify the client was called with headers
        scrapegraph_tools_integration.client.smartscraper.assert_called_once_with(
            website_url=test_url,
            user_prompt="Extract the complete raw HTML content of the entire webpage, including all tags, attributes, and structure. Return the full HTML source code.",
            render_heavy_js=False,
            headers=custom_headers,
        )

    def test_scrape_error_handling_integration(self, scrapegraph_tools_integration):
        """Test error handling in scrape method."""
        # Arrange
        scrapegraph_tools_integration.client.smartscraper.side_effect = Exception("Integration test error")

        # Act
        result = scrapegraph_tools_integration.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Integration test error"
        assert result_data["html"] == ""

    def test_scrape_response_format_consistency(self, scrapegraph_tools_integration):
        """Test that scrape method returns consistent response format."""
        # Arrange
        test_url = "https://example.com"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "result": "<html><body>Consistency Test</body></html>",
            "request_id": "req_consistency",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        
        # Check all required fields are present and have correct types
        assert isinstance(result_data["html"], str)
        assert isinstance(result_data["scrape_request_id"], str)
        assert isinstance(result_data["status"], str)
        assert isinstance(result_data["url"], str)
        assert isinstance(result_data["render_heavy_js"], bool)
        assert result_data["headers"] is None or isinstance(result_data["headers"], dict)
        assert result_data["error"] is None or isinstance(result_data["error"], str)

    def test_scrape_multiple_calls(self, scrapegraph_tools_integration):
        """Test multiple consecutive calls to scrape method."""
        # Arrange
        urls = [
            "https://example.com",
            "https://httpbin.org/html",
            "https://jsonplaceholder.typicode.com"
        ]
        
        scrapegraph_tools_integration.client.smartscraper.side_effect = [
            {
                "result": f"<html><body>Content for {url}</body></html>",
                "request_id": f"req_{i}",
                "status": "success",
            }
            for i, url in enumerate(urls)
        ]

        # Act & Assert
        for i, url in enumerate(urls):
            result = scrapegraph_tools_integration.scrape(website_url=url)
            result_data = json.loads(result)
            
            assert result_data["html"] == f"<html><body>Content for {url}</body></html>"
            assert result_data["url"] == url
            assert result_data["status"] == "success"

    def test_scrape_with_agent_error_handling(self, agent_with_scrape_tools):
        """Test scrape method error handling through agent."""
        # Arrange - Make the client raise an error
        agent_with_scrape_tools.tools[0].client.smartscraper.side_effect = Exception("Agent test error")

        # Act
        response = agent_with_scrape_tools.run("Use the scrape tool to get HTML from https://example.com")

        # Assert
        assert response is not None
        # The agent should handle the error gracefully
        assert hasattr(response, 'content') or hasattr(response, 'message')


class TestScrapeMethodWithDifferentResponseFormats:
    """Test scrape method with different API response formats."""

    def test_scrape_with_nested_html_field(self, scrapegraph_tools_integration):
        """Test scrape method when HTML is in nested result.html field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Nested HTML</body></html>"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "result": {"html": expected_html},
            "request_id": "req_nested_html",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_with_nested_content_field(self, scrapegraph_tools_integration):
        """Test scrape method when HTML is in nested result.content field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Nested Content</body></html>"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "result": {"content": expected_html},
            "request_id": "req_nested_content",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_with_direct_html_field(self, scrapegraph_tools_integration):
        """Test scrape method when HTML is in direct html field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Direct HTML</body></html>"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "html": expected_html,
            "request_id": "req_direct_html",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html

    def test_scrape_with_direct_content_field(self, scrapegraph_tools_integration):
        """Test scrape method when HTML is in direct content field."""
        # Arrange
        test_url = "https://example.com"
        expected_html = "<html><body>Direct Content</body></html>"
        
        scrapegraph_tools_integration.client.smartscraper.return_value = {
            "content": expected_html,
            "request_id": "req_direct_content",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_integration.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == expected_html


if __name__ == "__main__":
    pytest.main([__file__])
