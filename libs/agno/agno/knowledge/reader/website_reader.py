import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error, log_warning

try:
    from bs4 import BeautifulSoup, Tag  # noqa: F401
except ImportError:
    raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")


@dataclass
class WebsiteReader(Reader):
    """Reader for Websites"""

    max_depth: int = 3
    max_links: int = 10

    _visited: Set[str] = field(default_factory=set)
    _urls_to_crawl: List[Tuple[str, int]] = field(default_factory=list)

    def __init__(
        self,
        chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(),
        max_depth: int = 3,
        max_links: int = 10,
        timeout: int = 10,
        proxy: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.max_depth = max_depth
        self.max_links = max_links
        self.proxy = proxy
        self.timeout = timeout

        self._visited = set()
        self._urls_to_crawl = []

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Website readers."""
        return [
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def delay(self, min_seconds=1, max_seconds=3):
        """
        Introduce a random delay.

        :param min_seconds: Minimum number of seconds to delay. Default is 1.
        :param max_seconds: Maximum number of seconds to delay. Default is 3.
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        time.sleep(sleep_time)

    async def async_delay(self, min_seconds=1, max_seconds=3):
        """
        Introduce a random delay asynchronously.

        :param min_seconds: Minimum number of seconds to delay. Default is 1.
        :param max_seconds: Maximum number of seconds to delay. Default is 3.
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        await asyncio.sleep(sleep_time)

    def _get_primary_domain(self, url: str) -> str:
        """
        Extract primary domain from the given URL.

        :param url: The URL to extract the primary domain from.
        :return: The primary domain.
        """
        domain_parts = urlparse(url).netloc.split(".")
        # Return primary domain (excluding subdomains)
        return ".".join(domain_parts[-2:])

    def _extract_main_content(self, soup: BeautifulSoup) -> str:
        """
        Extracts the main content from a BeautifulSoup object.

        :param soup: The BeautifulSoup object to extract the main content from.
        :return: The main content.
        """

        def match(tag: Tag) -> bool:
            """
            Check if the tag matches any of the relevant tags or class names
            """
            if not isinstance(tag, Tag):
                return False

            if tag.name in ["article", "main", "section"]:
                return True

            classes_attr = tag.get("class")
            classes: List[str] = classes_attr if isinstance(classes_attr, list) else []
            content_classes = ["content", "main-content", "post-content", "entry-content", "article-body"]
            if any(cls in content_classes for cls in classes):
                return True

            # Check for common content IDs
            tag_id = tag.get("id", "")
            if tag_id in ["content", "main", "article"]:
                return True

            return False

        # Try to find main content element
        element = soup.find(match)
        if element and hasattr(element, "find_all"):
            # Remove common unwanted elements from the found content
            for unwanted in element.find_all(["script", "style", "nav", "header", "footer"]):
                unwanted.decompose()
            return element.get_text(strip=True, separator=" ")

        # Fallback: get full page content
        for unwanted in soup.find_all(["script", "style", "nav", "header", "footer"]):
            unwanted.decompose()
        return soup.get_text(strip=True, separator=" ")

    def crawl(self, url: str, starting_depth: int = 1) -> Dict[str, str]:
        """
        Crawls a website and returns a dictionary of URLs and their corresponding content.

        Parameters:
        - url (str): The starting URL to begin the crawl.
        - starting_depth (int, optional): The starting depth level for the crawl. Defaults to 1.

        Returns:
        - Dict[str, str]: A dictionary where each key is a URL and the corresponding value is the main
                          content extracted from that URL.

        Raises:
        - httpx.HTTPStatusError: If there's an HTTP status error.
        - httpx.RequestError: If there's a request-related error (connection, timeout, etc).

        Note:
        The function focuses on extracting the main content by prioritizing content inside common HTML tags
        like `<article>`, `<main>`, and `<div>` with class names such as "content", "main-content", etc.
        The crawler will also respect the `max_depth` attribute of the WebCrawler class, ensuring it does not
        crawl deeper than the specified depth.
        """
        num_links = 0
        crawler_result: Dict[str, str] = {}
        primary_domain = self._get_primary_domain(url)

        # Clear state so URLs from previous crawls aren't incorrectly skipped (matches async_crawl)
        self._visited = set()
        self._urls_to_crawl = [(url, starting_depth)]
        while self._urls_to_crawl:
            # Unpack URL and depth from the global list
            current_url, current_depth = self._urls_to_crawl.pop(0)

            # Skip if
            # - URL is already visited
            # - does not end with the primary domain,
            # - exceeds max depth
            # - exceeds max links
            if (
                current_url in self._visited
                or not urlparse(current_url).netloc.endswith(primary_domain)
                or (current_depth > self.max_depth and current_url != url)
                or num_links >= self.max_links
            ):
                continue

            self._visited.add(current_url)
            self.delay()

            try:
                log_debug(f"Crawling: {current_url}")

                response = (
                    httpx.get(current_url, timeout=self.timeout, proxy=self.proxy, follow_redirects=True)
                    if self.proxy
                    else httpx.get(current_url, timeout=self.timeout, follow_redirects=True)
                )
                response.raise_for_status()

                soup = BeautifulSoup(response.content, "html.parser")

                # Extract main content
                main_content = self._extract_main_content(soup)
                if main_content:
                    crawler_result[current_url] = main_content
                    num_links += 1

                # Add found URLs to the global list, with incremented depth
                for link in soup.find_all("a", href=True):
                    if not isinstance(link, Tag):
                        continue

                    href_str = str(link["href"])
                    full_url = urljoin(current_url, href_str)

                    if not isinstance(full_url, str):
                        continue

                    parsed_url = urlparse(full_url)
                    if parsed_url.netloc.endswith(primary_domain) and not any(
                        parsed_url.path.endswith(ext) for ext in [".pdf", ".jpg", ".png"]
                    ):
                        full_url_str = str(full_url)
                        if (
                            full_url_str not in self._visited
                            and (full_url_str, current_depth + 1) not in self._urls_to_crawl
                        ):
                            self._urls_to_crawl.append((full_url_str, current_depth + 1))

            except httpx.HTTPStatusError as e:
                # Log HTTP status errors but continue crawling other pages
                # Skip redirect errors (3xx) as they should be handled by follow_redirects
                if e.response.status_code >= 300 and e.response.status_code < 400:
                    log_debug(f"Redirect encountered for {current_url}, skipping: {e}")
                else:
                    log_warning(f"HTTP status error while crawling {current_url}: {e}")
                # For the initial URL, we should raise the error only if it's not a redirect
                if current_url == url and not crawler_result and not (300 <= e.response.status_code < 400):
                    raise
            except httpx.RequestError as e:
                # Log request errors but continue crawling other pages
                log_warning(f"Request error while crawling {current_url}: {e}")
                # For the initial URL, we should raise the error
                if current_url == url and not crawler_result:
                    raise
            except Exception as e:
                # Log other exceptions but continue crawling other pages
                log_warning(f"Failed to crawl {current_url}: {e}")
                # For the initial URL, we should raise the error
                if current_url == url and not crawler_result:
                    # Wrap non-HTTP exceptions in a RequestError
                    raise httpx.RequestError(f"Failed to crawl starting URL {url}: {str(e)}", request=None) from e

        # If we couldn't crawl any pages, raise an error
        if not crawler_result:
            raise httpx.RequestError(f"Failed to extract any content from {url}", request=None)

        return crawler_result

    async def async_crawl(self, url: str, starting_depth: int = 1) -> Dict[str, str]:
        """
        Asynchronously crawls a website and returns a dictionary of URLs and their corresponding content.

        Parameters:
        - url (str): The starting URL to begin the crawl.
        - starting_depth (int, optional): The starting depth level for the crawl. Defaults to 1.

        Returns:
        - Dict[str, str]: A dictionary where each key is a URL and the corresponding value is the main
                        content extracted from that URL.

        Raises:
        - httpx.HTTPStatusError: If there's an HTTP status error.
        - httpx.RequestError: If there's a request-related error (connection, timeout, etc).
        """
        num_links = 0
        crawler_result: Dict[str, str] = {}
        primary_domain = self._get_primary_domain(url)

        # Clear previously visited URLs and URLs to crawl
        self._visited = set()
        self._urls_to_crawl = [(url, starting_depth)]

        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            while self._urls_to_crawl and num_links < self.max_links:
                current_url, current_depth = self._urls_to_crawl.pop(0)

                if (
                    current_url in self._visited
                    or not urlparse(current_url).netloc.endswith(primary_domain)
                    or current_depth > self.max_depth
                    or num_links >= self.max_links
                ):
                    continue

                self._visited.add(current_url)
                await self.async_delay()

                try:
                    log_debug(f"Crawling asynchronously: {current_url}")
                    response = await client.get(current_url, timeout=self.timeout, follow_redirects=True)
                    response.raise_for_status()

                    soup = BeautifulSoup(response.content, "html.parser")

                    # Extract main content
                    main_content = self._extract_main_content(soup)
                    if main_content:
                        crawler_result[current_url] = main_content
                        num_links += 1

                    # Add found URLs to the list, with incremented depth
                    for link in soup.find_all("a", href=True):
                        if not isinstance(link, Tag):
                            continue

                        href_str = str(link["href"])
                        full_url = urljoin(current_url, href_str)

                        if not isinstance(full_url, str):
                            continue

                        parsed_url = urlparse(full_url)
                        if parsed_url.netloc.endswith(primary_domain) and not any(
                            parsed_url.path.endswith(ext) for ext in [".pdf", ".jpg", ".png"]
                        ):
                            full_url_str = str(full_url)
                            if (
                                full_url_str not in self._visited
                                and (full_url_str, current_depth + 1) not in self._urls_to_crawl
                            ):
                                self._urls_to_crawl.append((full_url_str, current_depth + 1))

                except httpx.HTTPStatusError as e:
                    # Log HTTP status errors but continue crawling other pages
                    log_warning(f"HTTP status error while crawling asynchronously {current_url}: {e}")
                    # For the initial URL, we should raise the error
                    if current_url == url and not crawler_result:
                        raise
                except httpx.RequestError as e:
                    # Log request errors but continue crawling other pages
                    log_warning(f"Request error while crawling asynchronously {current_url}: {e}")
                    # For the initial URL, we should raise the error
                    if current_url == url and not crawler_result:
                        raise
                except Exception as e:
                    # Log other exceptions but continue crawling other pages
                    log_warning(f"Failed to crawl asynchronously {current_url}: {e}")
                    # For the initial URL, we should raise the error
                    if current_url == url and not crawler_result:
                        # Wrap non-HTTP exceptions in a RequestError
                        raise httpx.RequestError(
                            f"Failed to crawl starting URL {url} asynchronously: {str(e)}", request=None
                        ) from e

        # If we couldn't crawl any pages, raise an error
        if not crawler_result:
            raise httpx.RequestError(f"Failed to extract any content from {url} asynchronously", request=None)

        return crawler_result

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
        """
        Reads a website and returns a list of documents.

        This function first converts the website into a dictionary of URLs and their corresponding content.
        Then iterates through the dictionary and returns chunks of content.

        :param url: The URL of the website to read.
        :return: A list of documents.
        :raises httpx.HTTPStatusError: If there's an HTTP status error.
        :raises httpx.RequestError: If there's a request-related error.
        """

        log_debug(f"Reading: {url}")
        try:
            crawler_result = self.crawl(url)
            documents = []
            for crawled_url, crawled_content in crawler_result.items():
                if self.chunk:
                    documents.extend(
                        self.chunk_document(
                            Document(
                                name=name or url,
                                id=str(crawled_url),
                                meta_data={"url": str(crawled_url)},
                                content=crawled_content,
                            )
                        )
                    )
                else:
                    documents.append(
                        Document(
                            name=name or url,
                            id=str(crawled_url),
                            meta_data={"url": str(crawled_url)},
                            content=crawled_content,
                        )
                    )
            return documents
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            log_error(f"Error reading website {url}: {e}")
            raise

    async def async_read(self, url: str, name: Optional[str] = None) -> List[Document]:
        """
        Asynchronously reads a website and returns a list of documents.

        This function first converts the website into a dictionary of URLs and their corresponding content.
        Then iterates through the dictionary and returns chunks of content.

        :param url: The URL of the website to read.
        :return: A list of documents.
        :raises httpx.HTTPStatusError: If there's an HTTP status error.
        :raises httpx.RequestError: If there's a request-related error.
        """
        log_debug(f"Reading asynchronously: {url}")
        try:
            crawler_result = await self.async_crawl(url)
            documents = []

            # Process documents in parallel
            async def process_document(crawled_url, crawled_content):
                if self.chunk:
                    doc = Document(
                        name=name or url,
                        id=str(crawled_url),
                        meta_data={"url": str(crawled_url)},
                        content=crawled_content,
                    )
                    chunks = self.chunk_document(doc)
                    return chunks
                else:
                    return [
                        Document(
                            name=name or url,
                            id=str(crawled_url),
                            meta_data={"url": str(crawled_url)},
                            content=crawled_content,
                        )
                    ]

            # Use asyncio.gather to process all documents in parallel
            tasks = [
                process_document(crawled_url, crawled_content)
                for crawled_url, crawled_content in crawler_result.items()
            ]

            results = await asyncio.gather(*tasks)

            # Flatten the results
            for doc_list in results:
                documents.extend(doc_list)

            return documents
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            log_error(f"Error reading website asynchronously {url}: {e}")
            raise
