import json
from unittest.mock import Mock, patch

import pytest

from agno.tools.trafilatura import TrafilaturaTools


@pytest.fixture
def mock_trafilatura_modules():
    """Mock all trafilatura module imports."""
    with (
        patch("agno.tools.trafilatura.extract") as mock_extract,
        patch("agno.tools.trafilatura.extract_metadata") as mock_extract_metadata,
        patch("agno.tools.trafilatura.fetch_url") as mock_fetch_url,
        patch("agno.tools.trafilatura.html2txt") as mock_html2txt,
        patch("agno.tools.trafilatura.reset_caches") as mock_reset_caches,
        patch("agno.tools.trafilatura.focused_crawler", create=True) as mock_crawler,
    ):
        yield {
            "extract": mock_extract,
            "extract_metadata": mock_extract_metadata,
            "fetch_url": mock_fetch_url,
            "html2txt": mock_html2txt,
            "reset_caches": mock_reset_caches,
            "focused_crawler": mock_crawler,
        }


@pytest.fixture
def trafilatura_tools(mock_trafilatura_modules):
    """Create a TrafilaturaTools instance with default settings."""
    return TrafilaturaTools()


@pytest.fixture
def custom_trafilatura_tools(mock_trafilatura_modules):
    """Create a TrafilaturaTools instance with custom settings."""
    return TrafilaturaTools(
        output_format="json",
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_formatting=True,
        include_links=True,
        with_metadata=True,
        favor_precision=True,
        target_language="en",
        deduplicate=True,
        max_tree_size=5000,
        max_crawl_urls=20,
        max_known_urls=50000,
    )


def create_mock_metadata_document(
    title="Test Title", author="Test Author", date="2024-01-01", url="https://example.com"
):
    """Helper function to create mock metadata document."""
    mock_doc = Mock()
    mock_doc.as_dict.return_value = {
        "title": title,
        "author": author,
        "date": date,
        "url": url,
        "text": "Sample text content",
    }
    return mock_doc


class TestTrafilaturaToolsInitialization:
    """Test class for TrafilaturaTools initialization."""

    def test_initialization_default(self, trafilatura_tools):
        """Test initialization with default values."""
        assert trafilatura_tools.name == "trafilatura_tools"
        assert trafilatura_tools.output_format == "txt"
        assert trafilatura_tools.include_comments is True
        assert trafilatura_tools.include_tables is True
        assert trafilatura_tools.include_images is False
        assert trafilatura_tools.include_formatting is False
        assert trafilatura_tools.include_links is False
        assert trafilatura_tools.with_metadata is False
        assert trafilatura_tools.favor_precision is False
        assert trafilatura_tools.favor_recall is False
        assert trafilatura_tools.target_language is None
        assert trafilatura_tools.deduplicate is False
        assert trafilatura_tools.max_tree_size is None
        assert trafilatura_tools.max_crawl_urls == 10
        assert trafilatura_tools.max_known_urls == 100000

        # Check registered functions - all tools included by default
        function_names = [func.name for func in trafilatura_tools.functions.values()]
        assert "extract_text" in function_names
        assert "extract_metadata_only" in function_names
        assert "html_to_text" in function_names
        assert "extract_batch" in function_names

    def test_initialization_custom(self, custom_trafilatura_tools):
        """Test initialization with custom values."""
        tools = custom_trafilatura_tools
        assert tools.output_format == "json"
        assert tools.include_comments is False
        assert tools.include_tables is True
        assert tools.include_images is True
        assert tools.include_formatting is True
        assert tools.include_links is True
        assert tools.with_metadata is True
        assert tools.favor_precision is True
        assert tools.target_language == "en"
        assert tools.deduplicate is True
        assert tools.max_tree_size == 5000
        assert tools.max_crawl_urls == 20
        assert tools.max_known_urls == 50000

        # Check all functions are registered
        function_names = [func.name for func in tools.functions.values()]
        assert "extract_text" in function_names
        assert "extract_metadata_only" in function_names
        assert "html_to_text" in function_names
        assert "extract_batch" in function_names

    def test_initialization_include_tools(self, mock_trafilatura_modules):
        """Test initialization with include_tools parameter."""
        tools = TrafilaturaTools(include_tools=["extract_text", "extract_batch"])
        function_names = [func.name for func in tools.functions.values()]
        assert "extract_text" in function_names
        assert "extract_batch" in function_names
        assert "extract_metadata_only" not in function_names
        assert "html_to_text" not in function_names

    def test_initialization_exclude_tools(self, mock_trafilatura_modules):
        """Test initialization with exclude_tools parameter."""
        tools = TrafilaturaTools(exclude_tools=["crawl_website", "html_to_text"])
        function_names = [func.name for func in tools.functions.values()]
        assert "extract_text" in function_names
        assert "extract_metadata_only" in function_names
        assert "extract_batch" in function_names
        assert "crawl_website" not in function_names
        assert "html_to_text" not in function_names

    @patch("agno.tools.trafilatura.SPIDER_AVAILABLE", False)
    def test_initialization_without_spider(self, mock_trafilatura_modules):
        """Test initialization when spider module is not available."""
        tools = TrafilaturaTools()
        function_names = [func.name for func in tools.functions.values()]
        # crawl_website should not be in functions when spider is not available
        assert "crawl_website" not in function_names


class TestExtractTextMethod:
    """Test class for extract_text method."""

    def test_extract_text_success(self, trafilatura_tools, mock_trafilatura_modules):
        """Test successful text extraction."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Test content</body></html>"
        mock_trafilatura_modules["extract"].return_value = "Extracted text content"

        # Execute
        result = trafilatura_tools.extract_text("https://example.com")

        # Assert
        assert result == "Extracted text content"
        mock_trafilatura_modules["fetch_url"].assert_called_once_with("https://example.com")
        mock_trafilatura_modules["extract"].assert_called_once()
        mock_trafilatura_modules["reset_caches"].assert_called_once()

    def test_extract_text_fetch_failure(self, trafilatura_tools, mock_trafilatura_modules):
        """Test extract_text when fetch_url fails."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = None

        # Execute
        result = trafilatura_tools.extract_text("https://example.com")

        # Assert
        assert "Error: Could not fetch content from URL" in result
        mock_trafilatura_modules["fetch_url"].assert_called_once_with("https://example.com")
        mock_trafilatura_modules["extract"].assert_not_called()

    def test_extract_text_with_custom_params(self, trafilatura_tools, mock_trafilatura_modules):
        """Test extract_text with custom output format."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Test content</body></html>"
        mock_trafilatura_modules["extract"].return_value = "Extracted text"

        # Execute with custom output format
        result = trafilatura_tools.extract_text("https://example.com", output_format="json")

        # Assert
        assert result == "Extracted text"
        # Verify extract was called with output format
        call_args = mock_trafilatura_modules["extract"].call_args
        assert call_args[1]["output_format"] == "json"

    def test_extract_text_exception_handling(self, trafilatura_tools, mock_trafilatura_modules):
        """Test extract_text exception handling."""
        # Setup mocks to raise exception
        mock_trafilatura_modules["fetch_url"].side_effect = Exception("Network error")

        # Execute
        result = trafilatura_tools.extract_text("https://example.com")

        # Assert
        assert "Error extracting text from https://example.com: Network error" in result


class TestExtractMetadataOnlyMethod:
    """Test class for extract_metadata_only method."""

    def test_extract_metadata_only_success(self, trafilatura_tools, mock_trafilatura_modules):
        """Test successful metadata extraction."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Test content</body></html>"
        mock_doc = create_mock_metadata_document()
        mock_trafilatura_modules["extract_metadata"].return_value = mock_doc

        # Execute
        result = trafilatura_tools.extract_metadata_only("https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["title"] == "Test Title"
        assert result_data["author"] == "Test Author"
        assert result_data["url"] == "https://example.com"
        mock_trafilatura_modules["reset_caches"].assert_called_once()

    def test_extract_metadata_only_fetch_failure(self, trafilatura_tools, mock_trafilatura_modules):
        """Test extract_metadata_only when fetch fails."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = None

        # Execute
        result = trafilatura_tools.extract_metadata_only("https://example.com")

        # Assert
        assert "Error: Could not fetch content from URL" in result

    def test_extract_metadata_only_extraction_failure(self, trafilatura_tools, mock_trafilatura_modules):
        """Test extract_metadata_only when extraction returns None."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Test content</body></html>"
        mock_trafilatura_modules["extract_metadata"].return_value = None

        # Execute
        result = trafilatura_tools.extract_metadata_only("https://example.com")

        # Assert
        assert "Error: Could not extract metadata" in result

    def test_extract_metadata_only_non_json_format(self, trafilatura_tools, mock_trafilatura_modules):
        """Test extract_metadata_only with non-JSON format."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Test content</body></html>"
        mock_doc = create_mock_metadata_document()
        mock_trafilatura_modules["extract_metadata"].return_value = mock_doc

        # Execute
        result = trafilatura_tools.extract_metadata_only("https://example.com", as_json=False)

        # Assert
        assert "Test Title" in result  # Should be string representation
        assert not result.startswith("{")  # Should not be JSON


class TestCrawlWebsiteMethod:
    """Test class for crawl_website method."""

    @patch("agno.tools.trafilatura.SPIDER_AVAILABLE", True)
    def test_crawl_website_success(self, trafilatura_tools, mock_trafilatura_modules):
        """Test successful website crawling."""
        # Setup mocks
        mock_to_visit = ["https://example.com/page1", "https://example.com/page2"]
        mock_known_links = ["https://example.com", "https://example.com/page1", "https://example.com/page2"]
        mock_trafilatura_modules["focused_crawler"].return_value = (mock_to_visit, mock_known_links)

        # Execute
        result = trafilatura_tools.crawl_website("https://example.com")

        # Assert
        result_data = json.loads(result)
        assert result_data["homepage"] == "https://example.com"
        assert len(result_data["to_visit"]) == 2
        assert len(result_data["known_links"]) == 3
        assert result_data["stats"]["urls_to_visit"] == 2
        assert result_data["stats"]["known_links_count"] == 3
        mock_trafilatura_modules["reset_caches"].assert_called_once()

    @patch("agno.tools.trafilatura.SPIDER_AVAILABLE", False)
    def test_crawl_website_spider_unavailable(self, trafilatura_tools, mock_trafilatura_modules):
        """Test crawl_website when spider is not available."""
        # Execute
        result = trafilatura_tools.crawl_website("https://example.com")

        # Assert
        assert "Error: Web crawling functionality not available" in result

    @patch("agno.tools.trafilatura.SPIDER_AVAILABLE", True)
    def test_crawl_website_with_content_extraction(self, trafilatura_tools, mock_trafilatura_modules):
        """Test crawl_website with content extraction enabled."""
        # Setup mocks
        mock_known_links = ["https://example.com/page1"]
        mock_trafilatura_modules["focused_crawler"].return_value = ([], mock_known_links)
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Content</body></html>"
        mock_trafilatura_modules["extract"].return_value = "Extracted content"

        # Execute
        result = trafilatura_tools.crawl_website("https://example.com", extract_content=True)

        # Assert
        result_data = json.loads(result)
        assert "extracted_content" in result_data
        assert result_data["extracted_content"]["https://example.com/page1"] == "Extracted content"


class TestHtmlToTextMethod:
    """Test class for html_to_text method."""

    def test_html_to_text_success(self, trafilatura_tools, mock_trafilatura_modules):
        """Test successful HTML to text conversion."""
        # Setup mocks
        mock_trafilatura_modules["html2txt"].return_value = "Converted text content"

        # Execute
        html_content = "<html><body><h1>Title</h1><p>Paragraph</p></body></html>"
        result = trafilatura_tools.html_to_text(html_content)

        # Assert
        assert result == "Converted text content"
        mock_trafilatura_modules["html2txt"].assert_called_once_with(html_content, clean=True)
        mock_trafilatura_modules["reset_caches"].assert_called_once()

    def test_html_to_text_with_clean_false(self, trafilatura_tools, mock_trafilatura_modules):
        """Test HTML to text conversion with clean=False."""
        # Setup mocks
        mock_trafilatura_modules["html2txt"].return_value = "Raw text content"

        # Execute
        html_content = "<html><body>Content</body></html>"
        result = trafilatura_tools.html_to_text(html_content, clean=False)

        # Assert
        assert result == "Raw text content"
        mock_trafilatura_modules["html2txt"].assert_called_once_with(html_content, clean=False)

    def test_html_to_text_empty_result(self, trafilatura_tools, mock_trafilatura_modules):
        """Test HTML to text conversion when result is empty."""
        # Setup mocks
        mock_trafilatura_modules["html2txt"].return_value = ""

        # Execute
        result = trafilatura_tools.html_to_text("<html></html>")

        # Assert
        assert "Error: Could not extract text from HTML content" in result

    def test_html_to_text_exception_handling(self, trafilatura_tools, mock_trafilatura_modules):
        """Test HTML to text exception handling."""
        # Setup mocks to raise exception
        mock_trafilatura_modules["html2txt"].side_effect = Exception("Conversion error")

        # Execute
        result = trafilatura_tools.html_to_text("<html></html>")

        # Assert
        assert "Error converting HTML to text: Conversion error" in result


class TestExtractBatchMethod:
    """Test class for extract_batch method."""

    def test_extract_batch_success(self, trafilatura_tools, mock_trafilatura_modules):
        """Test successful batch extraction."""
        # Setup mocks
        mock_trafilatura_modules["fetch_url"].return_value = "<html><body>Content</body></html>"
        mock_trafilatura_modules["extract"].return_value = "Extracted content"

        # Execute
        urls = ["https://example1.com", "https://example2.com"]
        result = trafilatura_tools.extract_batch(urls)

        # Assert
        result_data = json.loads(result)
        assert result_data["total_urls"] == 2
        assert result_data["successful_extractions"] == 2
        assert result_data["failed_extractions"] == 0
        assert len(result_data["results"]) == 2
        mock_trafilatura_modules["reset_caches"].assert_called_once()

    def test_extract_batch_partial_failure(self, trafilatura_tools, mock_trafilatura_modules):
        """Test batch extraction with partial failures."""

        # Setup mocks - first URL succeeds, second fails
        def fetch_side_effect(url):
            if "example1" in url:
                return "<html><body>Content</body></html>"
            return None

        mock_trafilatura_modules["fetch_url"].side_effect = fetch_side_effect
        mock_trafilatura_modules["extract"].return_value = "Extracted content"

        # Execute
        urls = ["https://example1.com", "https://example2.com"]
        result = trafilatura_tools.extract_batch(urls)

        # Assert
        result_data = json.loads(result)
        assert result_data["total_urls"] == 2
        assert result_data["successful_extractions"] == 1
        assert result_data["failed_extractions"] == 1
        assert len(result_data["failed_urls"]) == 1


class TestUtilityMethods:
    """Test class for utility methods."""

    def test_get_extraction_params_defaults(self, trafilatura_tools):
        """Test _get_extraction_params with default values."""
        params = trafilatura_tools._get_extraction_params()
        assert params["output_format"] == "txt"
        assert params["include_comments"] is True
        assert params["with_metadata"] is False

    def test_get_extraction_params_overrides(self, trafilatura_tools):
        """Test _get_extraction_params with parameter overrides."""
        params = trafilatura_tools._get_extraction_params(
            output_format="json", include_comments=False, with_metadata=True
        )
        assert params["output_format"] == "json"
        assert params["include_comments"] is False
        assert params["with_metadata"] is True


class TestToolkitIntegration:
    """Test class for toolkit integration."""

    def test_toolkit_registration_default(self, trafilatura_tools):
        """Test that tools are registered correctly with default configuration."""
        function_names = [func.name for func in trafilatura_tools.functions.values()]
        # Default configuration should include all available tools
        assert "extract_text" in function_names
        assert "extract_metadata_only" in function_names
        assert "html_to_text" in function_names
        assert "extract_batch" in function_names
        # crawl_website should be included if spider is available

    def test_toolkit_registration_custom(self, custom_trafilatura_tools):
        """Test that tools are registered correctly with custom configuration."""
        function_names = [func.name for func in custom_trafilatura_tools.functions.values()]
        # Custom configuration should include all enabled tools
        assert "extract_text" in function_names
        assert "extract_metadata_only" in function_names
        assert "html_to_text" in function_names
        assert "extract_batch" in function_names

    def test_toolkit_name(self, trafilatura_tools):
        """Test that toolkit has correct name."""
        assert trafilatura_tools.name == "trafilatura_tools"


if __name__ == "__main__":
    pytest.main([__file__])
