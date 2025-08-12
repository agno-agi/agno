import asyncio
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_warning

try:
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
except ImportError:
    raise ImportError("`crawl4ai` not installed. Please install using `pip install crawl4ai`")


class Crawl4aiTools(Toolkit):
    def __init__(
        self,
        max_length: Optional[int] = 5000,
        timeout: int = 60,
        use_pruning: bool = False,
        pruning_threshold: float = 0.48,
        bm25_threshold: float = 1.0,
        headless: bool = True,
        wait_until: str = "domcontentloaded",
        **kwargs,
    ):
        super().__init__(name="crawl4ai_tools", tools=[self.crawl], **kwargs)
        self.max_length = max_length
        self.timeout = timeout
        self.use_pruning = use_pruning
        self.pruning_threshold = pruning_threshold
        self.bm25_threshold = bm25_threshold
        self.wait_until = wait_until
        self.headless = headless

    def _build_config(self, search_query: Optional[str] = None) -> Dict[str, Any]:
        """Build CrawlerRunConfig parameters from toolkit settings."""
        config_params = {
            "page_timeout": self.timeout * 1000,  # Convert to milliseconds
            "wait_until": self.wait_until,
            "cache_mode": "bypass",  # Don't use cache for fresh results
            "verbose": False,
        }

        # Handle content filtering
        if self.use_pruning or search_query:
            try:
                from crawl4ai.content_filter_strategy import BM25ContentFilter, PruningContentFilter
                from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

                if search_query:
                    # Use BM25 for query-specific extraction
                    content_filter = BM25ContentFilter(user_query=search_query, bm25_threshold=self.bm25_threshold)
                    log_debug(f"Using BM25ContentFilter for query: {search_query}")
                else:
                    # Use pruning for general cleanup
                    content_filter = PruningContentFilter(
                        threshold=self.pruning_threshold, threshold_type="fixed", min_word_threshold=2
                    )
                    log_debug("Using PruningContentFilter for general cleanup")

                config_params["markdown_generator"] = DefaultMarkdownGenerator(content_filter=content_filter)
                log_debug("Using DefaultMarkdownGenerator with content_filter")
            except ImportError:
                # If advanced features not available, continue without them
                log_warning("crawl4ai.content_filter_strategy or crawl4ai.markdown_generation_strategy not installed")
                pass

        return config_params

    def crawl(self, url: Union[str, List[str]], search_query: Optional[str] = None) -> Union[str, Dict[str, str]]:
        """
        Crawl URLs and extract their text content.

        Args:
            url: Single URL string or list of URLs to crawl
            search_query: Optional query string to filter content using BM25 algorithm

        Returns:
            The extracted text content from the URL(s)
        """
        if not url:
            return "Error: No URL provided"

        # Handle single URL
        if isinstance(url, str):
            return asyncio.run(self._async_crawl(url, search_query))

        # Handle multiple URLs
        results = {}
        for single_url in url:
            results[single_url] = asyncio.run(self._async_crawl(single_url, search_query))
        return results

    async def _async_crawl(self, url: str, search_query: Optional[str] = None) -> str:
        """Crawl a single URL and extract content."""
        try:
            # Use BrowserConfig to suppress crawl4ai logs
            browser_config = BrowserConfig(
                headless=self.headless,
                verbose=False,
            )

            async with AsyncWebCrawler(config=browser_config) as crawler:
                # Build configuration from parameters
                config_params = self._build_config(search_query)

                config = CrawlerRunConfig(**config_params)
                log_debug(f"Crawling {url} with config: {config}")
                result = await crawler.arun(url=url, config=config)

                # Process the result
                if not result:
                    return "Error: No content found"

                log_debug(f"Result attributes: {dir(result)}")
                log_debug(f"Result success: {getattr(result, 'success', 'N/A')}")

                # Try to get markdown content
                content = ""
                if hasattr(result, "fit_markdown") and result.fit_markdown:
                    content = result.fit_markdown
                    log_debug("Using fit_markdown")
                elif hasattr(result, "markdown") and result.markdown:
                    if hasattr(result.markdown, "raw_markdown"):
                        content = result.markdown.raw_markdown
                        log_debug("Using markdown.raw_markdown")
                    else:
                        content = str(result.markdown)
                        log_debug("Using str(markdown)")
                else:
                    # Try to get any text content
                    if hasattr(result, "text"):
                        content = result.text
                        log_debug("Using text attribute")
                    elif hasattr(result, "html"):
                        log_warning("Only HTML available, no markdown extracted")
                        return "Error: Could not extract markdown from page"

                if not content:
                    log_warning(f"No content extracted. Result type: {type(result)}")
                    return "Error: No readable content extracted"

                log_debug(f"Extracted content length: {len(content)}")

                # Truncate if needed
                if self.max_length and len(content) > self.max_length:
                    content = content[: self.max_length] + "..."

                return content

        except Exception as e:
            log_warning(f"Exception during crawl: {str(e)}")
            return f"Error crawling {url}: {str(e)}"
