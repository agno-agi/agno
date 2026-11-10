"""Unit tests for Crawl4aiTools class."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.tools.crawl4ai import Crawl4aiTools


@pytest.fixture
def mock_async_crawler():
    """Create a mock AsyncWebCrawler."""
    with patch("agno.tools.crawl4ai.AsyncWebCrawler") as mock_crawler:
        mock_instance = AsyncMock()
        mock_crawler.return_value.__aenter__.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_browser_config():
    """Create a mock BrowserConfig."""
    with patch("agno.tools.crawl4ai.BrowserConfig") as mock_config:
        mock_instance = MagicMock()
        mock_config.return_value = mock_instance
        yield mock_config


@pytest.fixture
def mock_crawler_run_config():
    """Create a mock CrawlerRunConfig."""
    with patch("agno.tools.crawl4ai.CrawlerRunConfig") as mock_config:
        yield mock_config


@pytest.fixture
def crawl4ai_tools():
    """Create a Crawl4aiTools instance with default settings."""
    with (
        patch("agno.tools.crawl4ai.AsyncWebCrawler"),
        patch("agno.tools.crawl4ai.BrowserConfig"),
        patch("agno.tools.crawl4ai.CrawlerRunConfig"),
    ):
        return Crawl4aiTools()


@pytest.fixture
def custom_crawl4ai_tools():
    """Create a Crawl4aiTools instance with custom settings."""
    with (
        patch("agno.tools.crawl4ai.AsyncWebCrawler"),
        patch("agno.tools.crawl4ai.BrowserConfig"),
        patch("agno.tools.crawl4ai.CrawlerRunConfig"),
    ):
        return Crawl4aiTools(
            max_length=2000,
            timeout=30,
            use_pruning=True,
            pruning_threshold=0.6,
            bm25_threshold=2.0,
            wait_until="networkidle",
            headless=False,
        )


def create_mock_crawler_result(
    raw_markdown: str = "This is the extracted content from the webpage.",
    fit_markdown: str = None,
    html: str = "<html><body>Test content</body></html>",
    text: str = "Test text content",
    success: bool = True,
):
    """Helper function to create mock crawler result."""
    result = MagicMock()
    if raw_markdown:
        result.markdown = MagicMock()
        result.markdown.raw_markdown = raw_markdown
    else:
        result.markdown = None
    result.fit_markdown = fit_markdown
    result.html = html
    result.text = text
    result.success = success
    return result


def test_initialization_default(crawl4ai_tools):
    """Test initialization with default values."""
    assert crawl4ai_tools.name == "crawl4ai_tools"
    assert crawl4ai_tools.max_length == 5000
    assert crawl4ai_tools.timeout == 60
    assert crawl4ai_tools.use_pruning is False
    assert crawl4ai_tools.pruning_threshold == 0.48
    assert crawl4ai_tools.bm25_threshold == 1.0
    assert crawl4ai_tools.wait_until == "domcontentloaded"
    assert crawl4ai_tools.headless is True

    # Check registered functions
    function_names = [func.name for func in crawl4ai_tools.functions.values()]
    assert "crawl" in function_names
    assert len(crawl4ai_tools.functions) == 1


def test_initialization_custom(custom_crawl4ai_tools):
    """Test initialization with custom values."""
    assert custom_crawl4ai_tools.max_length == 2000
    assert custom_crawl4ai_tools.timeout == 30
    assert custom_crawl4ai_tools.use_pruning is True
    assert custom_crawl4ai_tools.pruning_threshold == 0.6
    assert custom_crawl4ai_tools.bm25_threshold == 2.0
    assert custom_crawl4ai_tools.wait_until == "networkidle"
    assert custom_crawl4ai_tools.headless is False


def test_crawl_no_url(crawl4ai_tools):
    """Test crawl with no URL provided."""
    result = crawl4ai_tools.crawl("")
    assert result == "Error: No URL provided"

    result = crawl4ai_tools.crawl([])
    assert result == "Error: No URL provided"


def test_crawl_single_url_success(crawl4ai_tools, mock_async_crawler, mock_browser_config, mock_crawler_run_config):
    """Test successful crawling of a single URL."""
    # Setup mock result
    mock_result = create_mock_crawler_result()
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Assert
    assert result == "This is the extracted content from the webpage."
    mock_browser_config.assert_called_once_with(headless=True, verbose=False)
    mock_crawler_run_config.assert_called_once()

    # Check config parameters
    config_call_args = mock_crawler_run_config.call_args[1]
    assert config_call_args["page_timeout"] == 60000  # 60 seconds in milliseconds
    assert config_call_args["wait_until"] == "domcontentloaded"
    assert config_call_args["cache_mode"] == "bypass"
    assert config_call_args["verbose"] is False


def test_crawl_with_search_query(crawl4ai_tools, mock_async_crawler, mock_browser_config, mock_crawler_run_config):
    """Test crawling with search query for content filtering."""
    # Setup mock result
    mock_result = create_mock_crawler_result()
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Mock the imports that happen inside _build_config
    with (
        patch("crawl4ai.content_filter_strategy.BM25ContentFilter") as mock_bm25,
        patch("crawl4ai.markdown_generation_strategy.DefaultMarkdownGenerator") as mock_markdown_gen,
    ):
        # Execute with search query
        result = crawl4ai_tools.crawl("https://example.com", search_query="machine learning")

        # Assert
        assert result == "This is the extracted content from the webpage."

        # Verify BM25 content filter is used
        mock_bm25.assert_called_once_with(user_query="machine learning", bm25_threshold=1.0)
        mock_markdown_gen.assert_called_once()


def test_crawl_with_fit_markdown(crawl4ai_tools, mock_async_crawler):
    """Test crawling when fit_markdown is available."""
    # Setup mock result with fit_markdown
    mock_result = create_mock_crawler_result(
        raw_markdown="This is the raw content.", fit_markdown="This is the filtered content."
    )
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Should return fit_markdown when available
    assert result == "This is the filtered content."


def test_crawl_length_truncation(crawl4ai_tools, mock_async_crawler):
    """Test content truncation when exceeding max_length."""
    # Setup mock with long content
    mock_result = create_mock_crawler_result(raw_markdown="A" * 10000)
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Assert truncation
    assert len(result) == 5003  # 5000 + "..."
    assert result.endswith("...")
    assert result[:5000] == "A" * 5000


def test_crawl_multiple_urls(crawl4ai_tools, mock_async_crawler):
    """Test crawling multiple URLs."""
    # Setup different results for each URL
    results = [
        create_mock_crawler_result(raw_markdown="Content from site 1"),
        create_mock_crawler_result(raw_markdown="Content from site 2"),
    ]

    # Configure arun to return different results
    call_count = 0

    async def mock_arun(url, config):
        nonlocal call_count
        result = results[call_count]
        call_count += 1
        return result

    mock_async_crawler.arun = mock_arun

    # Execute
    urls = ["https://site1.com", "https://site2.com"]
    result = crawl4ai_tools.crawl(urls)

    # Assert
    assert isinstance(result, dict)
    assert len(result) == 2
    assert result["https://site1.com"] == "Content from site 1"
    assert result["https://site2.com"] == "Content from site 2"


def test_crawl_error_handling(crawl4ai_tools, mock_async_crawler):
    """Test error handling during crawl."""
    mock_async_crawler.arun = AsyncMock(side_effect=Exception("Network error"))

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Assert error message
    assert "Error crawling https://example.com: Network error" in result


def test_crawl_no_content(crawl4ai_tools, mock_async_crawler):
    """Test handling of empty results."""
    mock_async_crawler.arun = AsyncMock(return_value=None)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Assert
    assert result == "Error: No content found"


def test_crawl_text_fallback(crawl4ai_tools, mock_async_crawler):
    """Test fallback to text when markdown is not available."""
    # Create result with only text
    mock_result = create_mock_crawler_result(raw_markdown=None, text="Plain text content")
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Should fall back to text
    assert result == "Plain text content"


def test_crawl_no_readable_content(crawl4ai_tools, mock_async_crawler):
    """Test error when no readable content is available."""
    # Create result with only HTML
    mock_result = create_mock_crawler_result(raw_markdown=None, text=None, html="<html><body>Test</body></html>")
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Should return error
    assert result == "Error: No readable content extracted"


def test_pruning_configuration(mock_async_crawler, mock_browser_config, mock_crawler_run_config):
    """Test pruning filter configuration."""
    # Mock the imports that happen inside _build_config
    with (
        patch("crawl4ai.content_filter_strategy.PruningContentFilter") as mock_pruning,
        patch("crawl4ai.markdown_generation_strategy.DefaultMarkdownGenerator") as mock_markdown_gen,
    ):
        # Create toolkit with pruning enabled
        toolkit = Crawl4aiTools(use_pruning=True, pruning_threshold=0.6)

        # Setup mock result
        mock_result = create_mock_crawler_result()
        mock_async_crawler.arun = AsyncMock(return_value=mock_result)

        # Execute
        result = toolkit.crawl("https://example.com")

        # Assert
        assert result == "This is the extracted content from the webpage."

        # Verify pruning filter is used
        mock_pruning.assert_called_once_with(threshold=0.6, threshold_type="fixed", min_word_threshold=2)
        mock_markdown_gen.assert_called_once()


def test_crawl_with_multiple_urls_and_errors(crawl4ai_tools, mock_async_crawler):
    """Test crawling multiple URLs with some failures."""
    # Configure arun to fail for second URL
    call_count = 0

    async def mock_arun(url, config):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise Exception("Connection failed")
        return create_mock_crawler_result(raw_markdown=f"Content from {url}")

    mock_async_crawler.arun = mock_arun

    # Execute
    urls = ["https://success.com", "https://fail.com"]
    result = crawl4ai_tools.crawl(urls)

    # Assert
    assert "Content from https://success.com" in result["https://success.com"]
    assert "Error crawling https://fail.com: Connection failed" in result["https://fail.com"]


def test_browser_config_proxy_forwarding(mock_async_crawler, mock_browser_config):
    tools = Crawl4aiTools(proxy_config={"proxy_config": {"server": "http://proxy:8080"}})

    mock_result = create_mock_crawler_result()
    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    tools.crawl("https://example.com")

    mock_browser_config.assert_called_once_with(
        headless=True,
        verbose=False,
        proxy_config={"server": "http://proxy:8080"},
    )


@patch("agno.tools.crawl4ai.log_warning")
def test_crawl_logging(mock_log_warning, crawl4ai_tools, mock_async_crawler):
    """Test logging during crawl operations."""
    # Setup result with only HTML (no markdown, no text)
    mock_result = create_mock_crawler_result(raw_markdown=None, text=None, html="<html><body>Test</body></html>")
    # Make sure result has html attribute but not text attribute
    mock_result.text = None
    delattr(mock_result, "text")  # Remove the text attribute entirely
    mock_result.html = "<html><body>Test</body></html>"

    mock_async_crawler.arun = AsyncMock(return_value=mock_result)

    # Execute
    result = crawl4ai_tools.crawl("https://example.com")

    # Check that error is returned and log was called
    assert result == "Error: Could not extract markdown from page"

    # Check warning was logged
    mock_log_warning.assert_called_once_with("Only HTML available, no markdown extracted")


@patch("agno.tools.crawl4ai.asyncio.run")
def test_asyncio_run_error(mock_asyncio_run, crawl4ai_tools):
    """Test handling of asyncio.run errors."""
    mock_asyncio_run.side_effect = RuntimeError("Event loop error")

    with pytest.raises(RuntimeError) as excinfo:
        crawl4ai_tools.crawl("https://example.com")

    assert "Event loop error" in str(excinfo.value)
