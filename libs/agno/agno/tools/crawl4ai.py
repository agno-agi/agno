import asyncio
from typing import Optional

from agno.tools import Toolkit

try:
    from crawl4ai import CacheMode, AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.content_filter_strategy import PruningContentFilter
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
except ImportError:
    raise ImportError(
        "`crawl4ai` not installed. Please install using `pip install crawl4ai`"
    )


class Crawl4aiTools(Toolkit):
    def __init__(
        self,
        max_length: Optional[int] = 1000,
        **kwargs,
    ):
        super().__init__(name="crawl4ai_tools", **kwargs)

        self.max_length = max_length

        self.register(self.web_crawler)

    def web_crawler(self, url: str, max_length: Optional[int] = None) -> str:
        """
        Crawls a website using crawl4ai's WebCrawler.

        :param url: The URL to crawl.
        :param max_length: The maximum length of the result.

        :return: The results of the crawling.
        """
        if url is None:
            return "No URL provided"

        # Run the async crawler function synchronously
        return asyncio.run(self._async_web_crawler(url, max_length))

    async def _async_web_crawler(
        self, url: str, max_length: Optional[int] = None
    ) -> str:
        """
        Asynchronous method to crawl a website using AsyncWebCrawler.

        :param url: The URL to crawl.

        :return: The results of the crawling as a markdown string, or None if no result.
        """

        async with AsyncWebCrawler(thread_safe=True) as crawler:
            config = CrawlerRunConfig(
                page_timeout=230000,
                wait_until="networkidle",
                session_id="my_session",
                cache_mode=CacheMode.BYPASS,
                remove_overlay_elements=True,
                excluded_tags=["nav", "footer", "aside", "header"],
                markdown_generator=DefaultMarkdownGenerator(
                    content_filter=PruningContentFilter(
                        threshold=0.48, threshold_type="fixed", min_word_threshold=0
                    ),
                    options={"ignore_links": False},
                ),
            )
            result = await crawler.arun(url=url, config=config)

            # Determine the length to use
            length = self.max_length or max_length
            if not result.markdown.raw_markdown:
                return "No result"

            # Remove spaces and truncate if length is specified
            if length:
                result = result.markdown.raw_markdown[:length]
                result = result.replace(" ", "")
                return result

            result = result.markdown.raw_markdown.replace(" ", "")
        return result
