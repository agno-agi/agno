from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import log_debug, logger

try:
    from firecrawl import FirecrawlApp
except ImportError:
    raise ImportError("The `firecrawl` package is not installed. Please install it via `pip install firecrawl-py`.")


@dataclass
class FirecrawlReader(Reader):
    api_key: Optional[str] = None
    params: Optional[Dict] = None
    mode: Literal["scrape", "crawl"] = "scrape"

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
        scraped_data = app.scrape_url(url, params=self.params)
        # print(scraped_data)
        content = scraped_data.get("markdown", "")

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
        crawl_result = app.crawl_url(url, params=self.params)
        documents = []

        # Extract data from crawl results
        results_data = crawl_result.get("data", [])
        for result in results_data:
            # Get markdown content, default to empty string if not found
            content = result.get("markdown", "")

            if content:  # Only create document if content exists
                if self.chunk:
                    documents.extend(self.chunk_document(Document(name=url, id=url, content=content)))
                else:
                    documents.append(Document(name=url, id=url, content=content))

        return documents

    def read(self, url: str) -> List[Document]:
        """

        Args:
            url: The URL of the website to scrape

        Returns:
            A list of documents
        """

        if self.mode == "scrape":
            return self.scrape(url)
        elif self.mode == "crawl":
            return self.crawl(url)
        else:
            raise NotImplementedError(f"Mode {self.mode} not implemented")
