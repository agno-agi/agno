"""Mock tests for ScrapeGraphTools scrape method error handling."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.tools.scrapegraph import ScrapeGraphTools


@pytest.fixture
def mock_scrapegraph_client():
    """Create a mock ScrapeGraph client for error testing."""
    return Mock()


@pytest.fixture
def scrapegraph_tools_mock(mock_scrapegraph_client):
    """Create ScrapeGraphTools instance with mocked client."""
    with patch("agno.tools.scrapegraph.Client") as mock_client_class:
        mock_client_class.return_value = mock_scrapegraph_client
        
        with patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}):
            tools = ScrapeGraphTools(scrape=True, smartscraper=False)
            tools.client = mock_scrapegraph_client
            return tools


class TestScrapeMethodErrorHandling:
    """Comprehensive error handling tests for the scrape method."""

    def test_scrape_connection_error(self, scrapegraph_tools_mock):
        """Test handling of connection errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = ConnectionError("Connection refused")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Connection refused"
        assert result_data["html"] == ""
        assert result_data["url"] == "https://example.com"

    def test_scrape_timeout_error(self, scrapegraph_tools_mock):
        """Test handling of timeout errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = TimeoutError("Request timed out")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Request timed out"

    def test_scrape_http_error(self, scrapegraph_tools_mock):
        """Test handling of HTTP errors."""
        # Arrange
        from requests.exceptions import HTTPError
        scrapegraph_tools_mock.client.smartscraper.side_effect = HTTPError("404 Not Found")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "404 Not Found"

    def test_scrape_ssl_error(self, scrapegraph_tools_mock):
        """Test handling of SSL errors."""
        # Arrange
        import ssl
        scrapegraph_tools_mock.client.smartscraper.side_effect = ssl.SSLError("SSL certificate verification failed")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "SSL certificate verification failed" in result_data["error"]

    def test_scrape_rate_limit_error(self, scrapegraph_tools_mock):
        """Test handling of rate limit errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = Exception("Rate limit exceeded")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Rate limit exceeded"

    def test_scrape_api_key_error(self, scrapegraph_tools_mock):
        """Test handling of API key errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = Exception("Invalid API key")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Invalid API key"

    def test_scrape_server_error(self, scrapegraph_tools_mock):
        """Test handling of server errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = Exception("Internal server error")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Internal server error"

    def test_scrape_network_unreachable(self, scrapegraph_tools_mock):
        """Test handling of network unreachable errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = ConnectionError("Network is unreachable")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Network is unreachable"

    def test_scrape_dns_resolution_error(self, scrapegraph_tools_mock):
        """Test handling of DNS resolution errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = ConnectionError("Name or service not known")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Name or service not known"

    def test_scrape_invalid_response_format(self, scrapegraph_tools_mock):
        """Test handling of invalid response format."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.return_value = "Invalid response format"

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"  # Should handle gracefully
        assert result_data["html"] == ""  # No HTML extracted from invalid format

    def test_scrape_empty_response(self, scrapegraph_tools_mock):
        """Test handling of empty response."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.return_value = {}

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["html"] == ""

    def test_scrape_none_response(self, scrapegraph_tools_mock):
        """Test handling of None response."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.return_value = None

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["html"] == ""

    def test_scrape_malformed_json_response(self, scrapegraph_tools_mock):
        """Test handling of malformed JSON response."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.return_value = {"result": "{"  # Malformed JSON

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["html"] == "{"  # Should extract the malformed content

    def test_scrape_unicode_error(self, scrapegraph_tools_mock):
        """Test handling of Unicode errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = UnicodeDecodeError(
            "utf-8", b"", 0, 1, "invalid start byte"
        )

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert "invalid start byte" in result_data["error"]

    def test_scrape_memory_error(self, scrapegraph_tools_mock):
        """Test handling of memory errors."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = MemoryError("Out of memory")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Out of memory"

    def test_scrape_keyboard_interrupt(self, scrapegraph_tools_mock):
        """Test handling of keyboard interrupt."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = KeyboardInterrupt("User interrupted")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "User interrupted"

    def test_scrape_generic_exception(self, scrapegraph_tools_mock):
        """Test handling of generic exceptions."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.side_effect = Exception("Generic error message")

        # Act
        result = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Generic error message"

    def test_scrape_error_with_parameters_preserved(self, scrapegraph_tools_mock):
        """Test that error response preserves input parameters."""
        # Arrange
        test_url = "https://example.com"
        custom_headers = {"User-Agent": "Test Bot"}
        scrapegraph_tools_mock.client.smartscraper.side_effect = Exception("Test error")

        # Act
        result = scrapegraph_tools_mock.scrape(
            website_url=test_url,
            render_heavy_js=True,
            headers=custom_headers
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "error"
        assert result_data["error"] == "Test error"
        assert result_data["url"] == test_url
        assert result_data["render_heavy_js"] is True
        assert result_data["headers"] == custom_headers

    def test_scrape_multiple_error_scenarios(self, scrapegraph_tools_mock):
        """Test multiple error scenarios in sequence."""
        # Arrange
        error_scenarios = [
            ConnectionError("Connection error"),
            TimeoutError("Timeout error"),
            Exception("Generic error"),
        ]
        
        scrapegraph_tools_mock.client.smartscraper.side_effect = error_scenarios

        # Act & Assert
        for i, expected_error in enumerate(error_scenarios):
            result = scrapegraph_tools_mock.scrape(website_url=f"https://example{i}.com")
            result_data = json.loads(result)
            
            assert result_data["status"] == "error"
            assert result_data["error"] == str(expected_error)

    def test_scrape_error_recovery(self, scrapegraph_tools_mock):
        """Test that scrape method recovers from errors."""
        # Arrange - First call fails, second succeeds
        scrapegraph_tools_mock.client.smartscraper.side_effect = [
            Exception("First call fails"),
            {
                "result": "<html><body>Success</body></html>",
                "request_id": "req_recovery",
                "status": "success",
            }
        ]

        # Act
        result1 = scrapegraph_tools_mock.scrape(website_url="https://example.com")
        result2 = scrapegraph_tools_mock.scrape(website_url="https://example.com")

        # Assert
        result1_data = json.loads(result1)
        result2_data = json.loads(result2)
        
        assert result1_data["status"] == "error"
        assert result2_data["status"] == "success"
        assert result2_data["html"] == "<html><body>Success</body></html>"


class TestScrapeMethodEdgeCases:
    """Test edge cases for the scrape method."""

    def test_scrape_very_long_url(self, scrapegraph_tools_mock):
        """Test scraping with very long URL."""
        # Arrange
        long_url = "https://example.com/" + "a" * 2000
        scrapegraph_tools_mock.client.smartscraper.return_value = {
            "result": "<html><body>Long URL test</body></html>",
            "request_id": "req_long_url",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_mock.scrape(website_url=long_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["url"] == long_url

    def test_scrape_url_with_special_characters(self, scrapegraph_tools_mock):
        """Test scraping with URL containing special characters."""
        # Arrange
        special_url = "https://example.com/path?param=value&other=test#fragment"
        scrapegraph_tools_mock.client.smartscraper.return_value = {
            "result": "<html><body>Special chars test</body></html>",
            "request_id": "req_special",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_mock.scrape(website_url=special_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["url"] == special_url

    def test_scrape_with_very_large_headers(self, scrapegraph_tools_mock):
        """Test scraping with very large headers."""
        # Arrange
        large_headers = {
            "User-Agent": "A" * 1000,
            "Custom-Header": "B" * 1000,
            "Another-Header": "C" * 1000,
        }
        scrapegraph_tools_mock.client.smartscraper.return_value = {
            "result": "<html><body>Large headers test</body></html>",
            "request_id": "req_large_headers",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_mock.scrape(
            website_url="https://example.com",
            headers=large_headers
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["headers"] == large_headers

    def test_scrape_with_none_headers(self, scrapegraph_tools_mock):
        """Test scraping with None headers."""
        # Arrange
        scrapegraph_tools_mock.client.smartscraper.return_value = {
            "result": "<html><body>None headers test</body></html>",
            "request_id": "req_none_headers",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_mock.scrape(
            website_url="https://example.com",
            headers=None
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["headers"] is None

    def test_scrape_with_empty_string_headers(self, scrapegraph_tools_mock):
        """Test scraping with empty string headers."""
        # Arrange
        empty_headers = {}
        scrapegraph_tools_mock.client.smartscraper.return_value = {
            "result": "<html><body>Empty headers test</body></html>",
            "request_id": "req_empty_headers",
            "status": "success",
        }

        # Act
        result = scrapegraph_tools_mock.scrape(
            website_url="https://example.com",
            headers=empty_headers
        )

        # Assert
        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["headers"] == empty_headers


if __name__ == "__main__":
    pytest.main([__file__])
