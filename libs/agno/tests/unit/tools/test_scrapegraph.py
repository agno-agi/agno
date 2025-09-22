"""Unit tests for ScrapeGraphTools class."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.tools.scrapegraph import ScrapeGraphTools


@pytest.fixture
def mock_scrapegraph_client():
    """Create a mock ScrapeGraph client."""
    mock_client = Mock()

    # Mock scrape method response
    mock_client.scrape.return_value = {
        "html": "<html><head><title>Test Page</title></head><body><h1>Hello World</h1><p>This is a test page.</p></body></html>",
        "request_id": "req_123456789",
    }

    # Mock smartscraper method response
    mock_client.smartscraper.return_value = {
        "result": "extracted data",
        "request_id": "req_123456789",
    }

    # Mock markdownify method response
    mock_client.markdownify.return_value = {
        "result": "# Test Page\n\nHello World\n\nThis is a test page.",
    }

    # Mock searchscraper method response
    mock_client.searchscraper.return_value = {
        "result": [{"title": "Test Result", "url": "https://example.com", "snippet": "Test snippet"}]
    }

    # Mock crawl method response
    mock_client.crawl.return_value = {"result": [{"page": "https://example.com", "data": {"title": "Test Page"}}]}

    # Mock agentic scraper response
    mock_client.agenticscraper.return_value = {
        "result": {"content": "Scraped content", "actions": ["navigate", "extract"]},
        "request_id": "req_agentic_123",
        "status": "success",
    }

    return mock_client


@pytest.fixture
def scrapegraph_tools(mock_scrapegraph_client):
    """Create a ScrapeGraphTools instance with mocked dependencies."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}),
    ):
        mock_client_class.return_value = mock_scrapegraph_client

        tools = ScrapeGraphTools(scrape=True, smartscraper=False)
        tools.client = mock_scrapegraph_client
        return tools


@pytest.fixture
def scrapegraph_tools_all_methods(mock_scrapegraph_client):
    """Create a ScrapeGraphTools instance with all methods enabled."""
    with (
        patch("agno.tools.scrapegraph.Client") as mock_client_class,
        patch("agno.tools.scrapegraph.sgai_logger"),
        patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}),
    ):
        mock_client_class.return_value = mock_scrapegraph_client

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


@pytest.fixture
def sample_html_content():
    """Sample HTML content for testing."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Page</title>
</head>
<body>
    <header>
        <h1>Welcome to Test Page</h1>
        <nav>
            <ul>
                <li><a href="/home">Home</a></li>
                <li><a href="/about">About</a></li>
                <li><a href="/contact">Contact</a></li>
            </ul>
        </nav>
    </header>
    <main>
        <section>
            <h2>Main Content</h2>
            <p>This is a test page with various HTML elements.</p>
            <div class="content">
                <img src="/test-image.jpg" alt="Test Image">
                <p>More content here...</p>
            </div>
        </section>
    </main>
    <footer>
        <p>&copy; 2024 Test Company. All rights reserved.</p>
    </footer>
    <script>
        console.log('Test script loaded');
    </script>
</body>
</html>"""


class TestScrapeGraphToolsInitialization:
    """Test initialization and configuration of ScrapeGraphTools."""

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools(api_key="test_key")
            assert tools.api_key == "test_key"
            mock_client_class.assert_called_once_with(api_key="test_key")

    def test_init_with_env_api_key(self):
        """Test initialization with API key from environment."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "env_api_key"}),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools()
            assert tools.api_key == "env_api_key"
            mock_client_class.assert_called_once_with(api_key="env_api_key")

    def test_init_default_configuration(self):
        """Test initialization with default configuration."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools()

            # Check that smartscraper is enabled by default
            tool_names = [func.__name__ for func in tools.tools]
            assert "smartscraper" in tool_names
            assert "scrape" not in tool_names  # scrape is disabled by default

    def test_init_with_scrape_enabled(self):
        """Test initialization with scrape method enabled."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools(scrape=True, smartscraper=False)

            tool_names = [func.__name__ for func in tools.tools]
            assert "scrape" in tool_names
            assert "smartscraper" not in tool_names

    def test_init_markdownify_when_smartscraper_disabled(self):
        """Test that markdownify is enabled when smartscraper is disabled."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools(smartscraper=False)

            tool_names = [func.__name__ for func in tools.tools]
            assert "markdownify" in tool_names
            assert "smartscraper" not in tool_names

    def test_init_all_methods_enabled(self):
        """Test initialization with all methods enabled."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools(
                smartscraper=True,
                markdownify=True,
                crawl=True,
                searchscraper=True,
                agentic_crawler=True,
                scrape=True,
            )

            tool_names = [func.__name__ for func in tools.tools]
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

    def test_toolkit_name(self):
        """Test that toolkit has correct name."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_key"}),
        ):
            mock_client_class.return_value = Mock()

            tools = ScrapeGraphTools()
            assert tools.name == "scrapegraph_tools"


class TestScrapeMethod:
    """Test the scrape method specifically."""

    def test_scrape_basic_functionality(self, scrapegraph_tools, sample_html_content):
        """Test basic scrape functionality."""
        # Arrange
        test_url = "https://example.com"
        scrapegraph_tools.client.scrape.return_value = {
            "html": sample_html_content,
            "request_id": "req_basic_123",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == sample_html_content
        assert result_data["request_id"] == "req_basic_123"

        # Verify client was called correctly
        scrapegraph_tools.client.scrape.assert_called_once_with(
            website_url=test_url,
            headers=None,
            render_heavy_js=False,
        )


class TestScrapeMethodErrorHandling:
    """Test error handling for the scrape method."""

    def test_scrape_connection_error(self, scrapegraph_tools):
        """Test handling of connection errors."""
        # Arrange
        scrapegraph_tools.client.smartscraper.side_effect = ConnectionError("Connection refused")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "Connection refused" in result

    def test_scrape_timeout_error(self, scrapegraph_tools):
        """Test handling of timeout errors."""
        # Arrange
        scrapegraph_tools.client.smartscraper.side_effect = TimeoutError("Request timed out")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "Request timed out" in result

    def test_scrape_api_error_response(self, scrapegraph_tools):
        """Test handling of API error responses."""
        # Arrange - SDK will raise exception for API errors
        scrapegraph_tools.client.scrape.side_effect = Exception("Invalid API key")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "Invalid API key" in result

    def test_scrape_network_error(self, scrapegraph_tools):
        """Test handling of network errors."""
        # Arrange
        scrapegraph_tools.client.scrape.side_effect = OSError("Network unreachable")

        # Act
        result = scrapegraph_tools.scrape(website_url="https://example.com")

        # Assert
        assert result.startswith("Error:")
        assert "Network unreachable" in result

    def test_scrape_with_custom_headers(self, scrapegraph_tools, sample_html_content):
        """Test scrape with custom headers."""
        # Arrange
        test_url = "https://example.com"
        custom_headers = {
            "User-Agent": "Custom Test Bot",
            "Accept": "text/html,application/xhtml+xml",
        }

        scrapegraph_tools.client.scrape.return_value = {
            "html": sample_html_content,
            "request_id": "req_headers_123",
        }

        # Act
        result = scrapegraph_tools.scrape(website_url=test_url, headers=custom_headers)

        # Assert
        result_data = json.loads(result)
        assert result_data["html"] == sample_html_content
        assert result_data["request_id"] == "req_headers_123"

        scrapegraph_tools.client.scrape.assert_called_once_with(
            website_url=test_url,
            headers=custom_headers,
            render_heavy_js=False,
        )

    def test_scrape_with_render_heavy_js_init(self, sample_html_content):
        """Test scrape with render_heavy_js set in initialization."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}),
        ):
            mock_client_instance = Mock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.scrape.return_value = {
                "html": sample_html_content,
                "request_id": "req_js_123",
            }

            # Create tools with render_heavy_js=True
            tools = ScrapeGraphTools(scrape=True, render_heavy_js=True)

            # Act
            result = tools.scrape(website_url="https://spa-website.com")

            # Assert
            result_data = json.loads(result)
            assert result_data["html"] == sample_html_content

            # Verify render_heavy_js=True was used
            mock_client_instance.scrape.assert_called_once_with(
                website_url="https://spa-website.com",
                headers=None,
                render_heavy_js=True,  # Should use init setting
            )

    def test_searchscraper_with_render_heavy_js_init(self):
        """Test searchscraper with render_heavy_js set in initialization."""
        with (
            patch("agno.tools.scrapegraph.Client") as mock_client_class,
            patch("agno.tools.scrapegraph.sgai_logger"),
            patch.dict(os.environ, {"SGAI_API_KEY": "test_api_key"}),
        ):
            mock_client_instance = Mock()
            mock_client_class.return_value = mock_client_instance
            mock_client_instance.searchscraper.return_value = {
                "result": ["search result 1", "search result 2"],
                "request_id": "req_search_123",
            }

            # Create tools with render_heavy_js=True
            tools = ScrapeGraphTools(searchscraper=True, render_heavy_js=True)

            # Act
            result = tools.searchscraper(user_prompt="search query")

            # Assert
            result_data = json.loads(result)
            assert isinstance(result_data, list)

            # Verify render_heavy_js=True was used
            mock_client_instance.searchscraper.assert_called_once_with(
                user_prompt="search query",
                render_heavy_js=True,  # Should use init setting
            )


class TestOtherMethods:
    """Test other ScrapeGraphTools methods."""

    def test_smartscraper_method(self, scrapegraph_tools_all_methods):
        """Test smartscraper method."""
        # Act
        result = scrapegraph_tools_all_methods.smartscraper(
            url="https://example.com", prompt="Extract all text content"
        )

        # Assert
        # Result is directly the extracted data (simplified)
        result_data = json.loads(result)
        assert result_data == "extracted data"
        scrapegraph_tools_all_methods.client.smartscraper.assert_called_once()

    def test_markdownify_method(self, scrapegraph_tools_all_methods):
        """Test markdownify method."""
        # Act
        result = scrapegraph_tools_all_methods.markdownify(url="https://example.com")

        # Assert
        assert "# Test Page" in result
        scrapegraph_tools_all_methods.client.markdownify.assert_called_once()

    def test_searchscraper_method(self, scrapegraph_tools_all_methods):
        """Test searchscraper method."""
        # Act
        result = scrapegraph_tools_all_methods.searchscraper(user_prompt="search query")

        # Assert
        result_data = json.loads(result)
        assert isinstance(result_data, list)
        scrapegraph_tools_all_methods.client.searchscraper.assert_called_once_with(
            user_prompt="search query", render_heavy_js=False
        )

    def test_crawl_method(self, scrapegraph_tools_all_methods):
        """Test crawl method."""
        # Act
        result = scrapegraph_tools_all_methods.crawl(
            url="https://example.com",
            prompt="Extract data",
            schema={"type": "object", "properties": {"title": {"type": "string"}}},
        )

        # Assert
        result_data = json.loads(result)
        assert "result" in result_data
        scrapegraph_tools_all_methods.client.crawl.assert_called_once_with(
            url="https://example.com",
            prompt="Extract data",
            data_schema={"type": "object", "properties": {"title": {"type": "string"}}},
            cache_website=True,
            depth=2,
            max_pages=2,
            same_domain_only=True,
            batch_size=1,
        )

    def test_agentic_crawler_method(self, scrapegraph_tools_all_methods):
        """Test agentic crawler method."""
        # Act
        result = scrapegraph_tools_all_methods.agentic_crawler(
            url="https://example.com", steps=["navigate to page", "extract content"]
        )

        # Assert
        result_data = json.loads(result)
        assert "result" in result_data
        scrapegraph_tools_all_methods.client.agenticscraper.assert_called_once()


class TestAgentIntegration:
    """Test integration with Agno agents."""

    @pytest.fixture
    def agent_with_scrape_tools(self, scrapegraph_tools):
        """Create an agent with ScrapeGraphTools for integration tests."""
        with patch("agno.models.openai.OpenAIChat"):  # Mock the model
            return Agent(
                name="Scrape Test Agent",
                tools=[scrapegraph_tools],
                instructions=[
                    "You are a web scraping assistant.",
                    "Use the scrape tool to get HTML content from websites.",
                ],
                show_tool_calls=True,
                markdown=True,
            )

    def test_agent_tool_registration(self, agent_with_scrape_tools):
        """Test that scrape tools are properly registered with agent."""
        # Check that the agent has the ScrapeGraphTools
        assert len(agent_with_scrape_tools.tools) == 1
        assert agent_with_scrape_tools.tools[0].name == "scrapegraph_tools"

    def test_scrape_tool_availability(self, scrapegraph_tools):
        """Test that scrape tool is available in the toolkit."""
        tool_names = [func.__name__ for func in scrapegraph_tools.tools]
        assert "scrape" in tool_names
