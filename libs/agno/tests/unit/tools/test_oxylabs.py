"""Unit tests for OxylabsTools class."""

import json
from unittest.mock import Mock, patch

import pytest

from agno.agent import Agent
from agno.tools.oxylabs import OxylabsTools


@pytest.fixture
def mock_agent():
    """Create a mock Agent instance."""
    return Mock(spec=Agent)


@pytest.fixture
def mock_oxylabs_client():
    """Create a mocked Oxylabs RealtimeClient with all resource methods stubbed."""
    with patch("agno.tools.oxylabs.RealtimeClient") as mock_realtime_client:
        # Primary client mock returned by the SDK constructor
        mock_client = Mock()

        # Mock nested resource clients
        mock_client.google = Mock()
        mock_client.amazon = Mock()
        mock_client.universal = Mock()

        # Configure the RealtimeClient constructor to return our mock
        mock_realtime_client.return_value = mock_client

        yield mock_client


@pytest.fixture
def mock_environment_variables():
    """Mock environment variables for Oxylabs credentials."""
    with patch.dict("os.environ", {"OXYLABS_USERNAME": "test_user", "OXYLABS_PASSWORD": "test_pass"}):
        yield


def create_mock_response(results=None, status_code=200):
    """Helper to create a mock response object matching the SDK structure."""
    mock_response = Mock()
    mock_response.results = []

    if results:
        for result_data in results:
            mock_result = Mock()
            mock_result.content = result_data.get("content")
            mock_result.status_code = result_data.get("status_code", status_code)
            mock_result.content_parsed = result_data.get("content_parsed")
            mock_response.results.append(mock_result)

    return mock_response


class TestOxylabsToolsInitialization:
    """Test cases for OxylabsTools initialization."""

    def test_init_with_credentials(self, mock_oxylabs_client):
        """Test initialization with provided credentials."""
        tools = OxylabsTools(username="test_user", password="test_pass")

        assert tools.username == "test_user"
        assert tools.password == "test_pass"
        assert tools.client is not None

    def test_init_with_env_variables(self, mock_oxylabs_client, mock_environment_variables):
        """Test initialization with environment variables."""
        tools = OxylabsTools()

        assert tools.username == "test_user"
        assert tools.password == "test_pass"
        assert tools.client is not None

    def test_init_without_credentials(self):
        """Test initialization failure without credentials."""
        # Ensure no environment variables are set
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No Oxylabs credentials provided"):
                OxylabsTools()

    def test_init_partial_credentials(self):
        """Test initialization failure with partial credentials."""
        # Ensure no environment variables are set
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="No Oxylabs credentials provided"):
                OxylabsTools(username="test_user")


class TestSearchGoogle:
    """Test cases for search_google method."""

    def test_search_google_success(self, mock_oxylabs_client, mock_environment_variables):
        """Test successful Google search."""
        # Arrange
        mock_response = create_mock_response(
            results=[
                {
                    "content": {
                        "results": {
                            "organic": [
                                {
                                    "title": "Test Result",
                                    "url": "https://example.com",
                                    "desc": "Test description",
                                    "pos": 1,
                                }
                            ]
                        }
                    },
                    "status_code": 200,
                }
            ]
        )
        mock_oxylabs_client.google.scrape_search.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.search_google(query="test query", domain_code="com")

        # Assert
        mock_oxylabs_client.google.scrape_search.assert_called_once_with(query="test query", domain="com", parse=True)

        result_data = json.loads(result)
        assert result_data["tool"] == "search_google"
        assert result_data["query"] == "test query"
        assert "results" in result_data

    def test_search_google_empty_query(self, mock_oxylabs_client, mock_environment_variables):
        """Test Google search with empty query."""
        tools = OxylabsTools()

        result = tools.search_google(query="")

        result_data = json.loads(result)
        assert "error" in result_data
        assert result_data["tool"] == "search_google"
        assert "cannot be empty" in result_data["error"]

    def test_search_google_invalid_domain(self, mock_oxylabs_client, mock_environment_variables):
        """Test Google search with invalid domain."""
        tools = OxylabsTools()

        result = tools.search_google(query="test", domain_code="x" * 15)

        result_data = json.loads(result)
        assert "error" in result_data
        assert result_data["tool"] == "search_google"
        assert "valid string" in result_data["error"]


class TestGetAmazonProduct:
    """Test cases for get_amazon_product method."""

    def test_get_amazon_product_success(self, mock_oxylabs_client, mock_environment_variables):
        """Test successful Amazon product lookup."""
        # Arrange
        mock_response = create_mock_response(
            results=[
                {
                    "content": {"title": "Test Product", "price": 29.99, "currency": "USD", "rating": 4.5},
                    "status_code": 200,
                }
            ]
        )
        mock_oxylabs_client.amazon.scrape_product.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.get_amazon_product(asin="B08N5WRWNW", domain_code="com")

        # Assert
        mock_oxylabs_client.amazon.scrape_product.assert_called_once_with(query="B08N5WRWNW", domain="com", parse=True)

        result_data = json.loads(result)
        assert result_data["tool"] == "get_amazon_product"
        assert result_data["asin"] == "B08N5WRWNW"
        assert "product_info" in result_data

    def test_get_amazon_product_invalid_asin(self, mock_oxylabs_client, mock_environment_variables):
        """Test Amazon product lookup with invalid ASIN."""
        tools = OxylabsTools()

        result = tools.get_amazon_product(asin="INVALID")

        result_data = json.loads(result)
        assert "error" in result_data
        assert result_data["tool"] == "get_amazon_product"
        assert "Invalid ASIN format" in result_data["error"]


class TestSearchAmazonProducts:
    """Test cases for search_amazon_products method."""

    def test_search_amazon_products_success(self, mock_oxylabs_client, mock_environment_variables):
        """Test successful Amazon search."""
        # Arrange
        mock_response = create_mock_response(
            results=[
                {
                    "content": {
                        "results": {"organic": [{"title": "Test Product", "asin": "B08N5WRWNW", "price": 29.99}]}
                    },
                    "status_code": 200,
                }
            ]
        )
        mock_oxylabs_client.amazon.scrape_search.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.search_amazon_products(query="wireless headphones", domain_code="com")

        # Assert
        mock_oxylabs_client.amazon.scrape_search.assert_called_once_with(
            query="wireless headphones", domain="com", parse=True
        )

        result_data = json.loads(result)
        assert result_data["tool"] == "search_amazon_products"
        assert result_data["query"] == "wireless headphones"
        assert "products" in result_data

    def test_search_amazon_products_empty_query(self, mock_oxylabs_client, mock_environment_variables):
        """Test Amazon search with empty query."""
        tools = OxylabsTools()

        result = tools.search_amazon_products(query="")

        result_data = json.loads(result)
        assert "error" in result_data
        assert result_data["tool"] == "search_amazon_products"
        assert "cannot be empty" in result_data["error"]


class TestScrapeWebsite:
    """Test cases for scrape_website method."""

    def test_scrape_website_success(self, mock_oxylabs_client, mock_environment_variables):
        """Test successful website scraping."""
        # Arrange
        mock_response = create_mock_response(
            results=[{"content": "<html><body>Test Content</body></html>", "status_code": 200}]
        )
        mock_oxylabs_client.universal.scrape_url.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.scrape_website(url="https://example.com", render_javascript=False)

        # Assert
        mock_oxylabs_client.universal.scrape_url.assert_called_once_with(
            url="https://example.com", render=None, parse=True
        )

        result_data = json.loads(result)
        assert result_data["tool"] == "scrape_website"
        assert result_data["url"] == "https://example.com"
        assert "content_info" in result_data

    def test_scrape_website_invalid_url(self, mock_oxylabs_client, mock_environment_variables):
        """Test website scraping with invalid URL."""
        tools = OxylabsTools()

        result = tools.scrape_website(url="not-a-url")

        result_data = json.loads(result)
        assert "error" in result_data
        assert result_data["tool"] == "scrape_website"
        assert "Invalid URL format" in result_data["error"]

    def test_scrape_website_with_javascript(self, mock_oxylabs_client, mock_environment_variables):
        """Test website scraping with JavaScript rendering."""
        # Arrange
        mock_response = create_mock_response(
            results=[{"content": "<html><body>Rendered Content</body></html>", "status_code": 200}]
        )
        mock_oxylabs_client.universal.scrape_url.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.scrape_website(url="https://example.com", render_javascript=True)

        # Assert
        result_data = json.loads(result)
        assert result_data["tool"] == "scrape_website"
        assert result_data["content_info"]["javascript_rendered"] is True


class TestErrorHandling:
    """Test cases for error handling."""

    def test_api_exception_handling(self, mock_oxylabs_client, mock_environment_variables):
        """Test handling of API exceptions."""
        # Arrange
        mock_oxylabs_client.google.scrape_search.side_effect = Exception("API Error")
        tools = OxylabsTools()

        # Act
        result = tools.search_google(query="test")

        # Assert
        result_data = json.loads(result)
        assert "error" in result_data
        assert result_data["tool"] == "search_google"
        assert "API Error" in result_data["error"]


class TestResponseFormatting:
    """Test cases for response formatting."""

    def test_format_response_with_parsed_content(self, mock_oxylabs_client, mock_environment_variables):
        """Test response formatting with parsed content."""
        # Arrange
        mock_response = create_mock_response(
            results=[
                {
                    "content_parsed": Mock(
                        results=Mock(
                            raw={
                                "organic": [
                                    {
                                        "title": "Test",
                                        "url": "https://example.com",
                                        "desc": "Test description",
                                        "pos": 1,
                                    }
                                ]
                            }
                        )
                    ),
                    "status_code": 200,
                }
            ]
        )
        mock_oxylabs_client.google.scrape_search.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.search_google(query="test")

        # Assert
        result_data = json.loads(result)
        assert result_data["tool"] == "search_google"
        assert result_data["query"] == "test"
        assert len(result_data["results"]) == 1
        assert result_data["results"][0]["title"] == "Test"

    def test_format_response_empty_results(self, mock_oxylabs_client, mock_environment_variables):
        """Test response formatting with empty results."""
        # Arrange
        mock_response = create_mock_response(results=[])
        mock_oxylabs_client.google.scrape_search.return_value = mock_response

        tools = OxylabsTools()

        # Act
        result = tools.search_google(query="test")

        # Assert
        result_data = json.loads(result)
        assert result_data["tool"] == "search_google"
        assert result_data["query"] == "test"
        assert len(result_data["results"]) == 0
