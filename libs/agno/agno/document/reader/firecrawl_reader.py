import asyncio
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy
from agno.document.reader.base import Reader
from agno.utils.log import log_debug, logger

try:
    from firecrawl import FirecrawlApp  # type: ignore[attr-defined]
except ImportError:
    raise ImportError("The `firecrawl` package is not installed. Please install it via `pip install firecrawl-py`.")


@dataclass
class FirecrawlReader(Reader):
    api_key: Optional[str] = None
    params: Optional[Dict] = None
    mode: Literal["scrape", "crawl"] = "scrape"

    def __init__(
        self,
        api_key: Optional[str] = None,
        params: Optional[Dict] = None,
        mode: Literal["scrape", "crawl"] = "scrape",
        chunk: bool = True,
        chunk_size: int = 5000,
        chunking_strategy: Optional[ChunkingStrategy] = None,
    ) -> None:
        # Initialise base Reader (handles chunk_size / strategy)
        super().__init__(chunk=chunk, chunk_size=chunk_size, chunking_strategy=chunking_strategy)

        # Firecrawl-specific attributes
        self.api_key = api_key
        self.params = params
        self.mode = mode

    def scrape(self, url: str) -> List[Document]:
        """
        Scrapes a website and returns a list of documents.

        Args:
            url: The URL of the website to scrape

        Returns:
            A list of documents
        """

        log_debug(f"Scraping: {url}")

        app = FirecrawlApp(api_key=self.api_key)

        if self.params:
            scraped_data = app.scrape_url(url, **self.params)
        else:
            scraped_data = app.scrape_url(url)
        if isinstance(scraped_data, dict):
            content = scraped_data.get("markdown", "")
        else:
            content = getattr(scraped_data, "markdown", "")

        # Debug logging
        log_debug(f"Received content type: {type(content)}")
        log_debug(f"Content empty: {not bool(content)}")

        # Ensure content is a string
        if content is None:
            content = ""  # or you could use metadata to create a meaningful message
            logger.warning(f"No content received for URL: {url}")

        documents = []
        if self.chunk and content:  # Only chunk if there's content
            documents.extend(self.chunk_document(Document(name=url, id=url, content=content)))
        else:
            documents.append(Document(name=url, id=url, content=content))
        return documents

    async def async_scrape(self, url: str) -> List[Document]:
        """
        Asynchronously scrapes a website and returns a list of documents.

        Args:
            url: The URL of the website to scrape

        Returns:
            A list of documents
        """
        log_debug(f"Async scraping: {url}")

        # Use asyncio.to_thread to run the synchronous scrape in a thread
        return await asyncio.to_thread(self.scrape, url)

    def crawl(self, url: str) -> List[Document]:
        """
        Crawls a website and returns a list of documents.

        Args:
            url: The URL of the website to crawl

        Returns:
            A list of documents
        """
        log_debug(f"Crawling: {url}")

        app = FirecrawlApp(api_key=self.api_key)

        if self.params:
            crawl_result = app.crawl_url(url, **self.params)
        else:
            crawl_result = app.crawl_url(url)
        documents = []

        if isinstance(crawl_result, dict):
            results_data = crawl_result.get("data", [])
        else:
            results_data = getattr(crawl_result, "data", [])
        for result in results_data:
            # Get markdown content, default to empty string if not found
            if isinstance(result, dict):
                content = result.get("markdown", "")
            else:
                content = getattr(result, "markdown", "")

            if content:  # Only create document if content exists
                if self.chunk:
                    documents.extend(self.chunk_document(Document(name=url, id=url, content=content)))
                else:
                    documents.append(Document(name=url, id=url, content=content))

        return documents

    async def async_crawl(self, url: str) -> List[Document]:
        """
        Asynchronously crawls a website and returns a list of documents.

        Args:
            url: The URL of the website to crawl

        Returns:
            A list of documents
        """
        log_debug(f"Async crawling: {url}")

        # Use asyncio.to_thread to run the synchronous crawl in a thread
        return await asyncio.to_thread(self.crawl, url)

    def read(self, url: str) -> List[Document]:
        """
        Reads from a URL based on the mode setting.

        Args:
            url: The URL of the website to process

        Returns:
            A list of documents
        """
        if self.mode == "scrape":
            return self.scrape(url)
        elif self.mode == "crawl":
            return self.crawl(url)
        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")

    async def async_read(self, url: str) -> List[Document]:
        """
        Asynchronously reads from a URL based on the mode setting.

        Args:
            url: The URL of the website to process

        Returns:
            A list of documents
        """
        if self.mode == "scrape":
            return await self.async_scrape(url)
        elif self.mode == "crawl":
            return await self.async_crawl(url)
        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")
