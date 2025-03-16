import asyncio
import httpx
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    from crawl4ai import AsyncWebCrawler, CacheMode
except ImportError:
    raise ImportError("`crawl4ai` not installed. Please install using `pip install crawl4ai`")


class Crawl4aiTools(Toolkit):
    def __init__(
        self,
        max_length: Optional[int] = 1000,
        expand_url: bool = False,
        retries: int = 3,
    ):
        super().__init__(name="crawl4ai_tools")

        self.max_length = max_length
        self.expand_url_flag = expand_url
        self.retries = retries

        self.register(self.web_crawler)
        if expand_url:
            self.register(self.expand_url)

    def expand_url(self, url: str) -> str:
        """
        Expands a shortened URL to its final destination using HTTP HEAD requests with retries.

        :param url: The URL to expand.

        :return: The final destination URL if successful; otherwise, returns the original URL.
        """
        timeout = 5
        for attempt in range(1, self.retries + 1):
            try:
                response = httpx.head(url,follow_redirects=True,timeout=timeout)
                final_url = response.url
                logger.info(f"expand_url: {url} expanded to {final_url} on attempt {attempt}")
                return str(final_url)
            except Exception as e:
                logger.error(f"Error expanding URL {url} on attempt {attempt}: {e}")

        return url


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

    async def _async_web_crawler(self, url: str, max_length: Optional[int] = None) -> str:
        """
        Asynchronous method to crawl a website using AsyncWebCrawler.

        :param url: The URL to crawl.

        :return: The results of the crawling as a markdown string, or None if no result.
        """

        async with AsyncWebCrawler(thread_safe=True) as crawler:
            result = await crawler.arun(url=url, cache_mode=CacheMode.BYPASS)

            # Determine the length to use
            length = self.max_length or max_length
            if not result.markdown:
                return "No result"

            # Remove spaces and truncate if length is specified
            if length:
                result = result.markdown[:length]
                result = result.replace(" ", "")
                return result

            result = result.markdown.replace(" ", "")
        return result
