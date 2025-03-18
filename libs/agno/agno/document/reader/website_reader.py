import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple
from urllib.parse import urljoin, urlparse

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.log import logger

try:
    from bs4 import BeautifulSoup, Tag  # noqa: F401
except ImportError:
    raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install it via `pip install httpx`.")


@dataclass
class WebsiteReader(Reader):
    """Reader for Websites"""

    max_depth: int = 3
    max_links: int = 10

    _visited: Set[str] = field(default_factory=set)
    _urls_to_crawl: List[Tuple[str, int]] = field(default_factory=list)

    def delay(self, min_seconds=1, max_seconds=3):
        """
        Introduce a random delay.

        :param min_seconds: Minimum number of seconds to delay. Default is 1.
        :param max_seconds: Maximum number of seconds to delay. Default is 3.
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        time.sleep(sleep_time)

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
        # Try to find main content by specific tags or class names
        for tag in ["article", "main"]:
            element = soup.find(tag)
            if element:
                return element.get_text(strip=True, separator=" ")

        for class_name in ["content", "main-content", "post-content"]:
            element = soup.find(class_=class_name)
            if element:
                return element.get_text(strip=True, separator=" ")

        return ""

    def crawl(self, url: str, starting_depth: int = 1) -> Dict[str, str]:
        """
        Crawls a website and returns a dictionary of URLs and their corresponding content.

        Parameters:
        - url (str): The starting URL to begin the crawl.
        - starting_depth (int, optional): The starting depth level for the crawl. Defaults to 1.

        Returns:
        - Dict[str, str]: A dictionary where each key is a URL and the corresponding value is the main
                          content extracted from that URL.

        Note:
        The function focuses on extracting the main content by prioritizing content inside common HTML tags
        like `<article>`, `<main>`, and `<div>` with class names such as "content", "main-content", etc.
        The crawler will also respect the `max_depth` attribute of the WebCrawler class, ensuring it does not
        crawl deeper than the specified depth.
        """
        num_links = 0
        crawler_result: Dict[str, str] = {}
        primary_domain = self._get_primary_domain(url)
        # Add starting URL with its depth to the global list
        self._urls_to_crawl.append((url, starting_depth))
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
                or current_depth > self.max_depth
                or num_links >= self.max_links
            ):
                continue

            self._visited.add(current_url)
            self.delay()

            try:
                logger.debug(f"Crawling: {current_url}")
                response = httpx.get(current_url, timeout=10)

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

            except Exception as e:
                logger.warning(f"Failed to crawl: {current_url}: {e}")
                pass

        return crawler_result

    def read(self, url: str) -> List[Document]:
        """
        Reads a website and returns a list of documents.

        This function first converts the website into a dictionary of URLs and their corresponding content.
        Then iterates through the dictionary and returns chunks of content.

        :param url: The URL of the website to read.
        :return: A list of documents.
        """

        logger.debug(f"Reading: {url}")
        crawler_result = self.crawl(url)
        documents = []
        for crawled_url, crawled_content in crawler_result.items():
            if self.chunk:
                documents.extend(
                    self.chunk_document(
                        Document(
                            name=url, id=str(crawled_url), meta_data={"url": str(crawled_url)}, content=crawled_content
                        )
                    )
                )
            else:
                documents.append(
                    Document(
                        name=url,
                        id=str(crawled_url),
                        meta_data={"url": str(crawled_url)},
                        content=crawled_content,
                    )
                )
        return documents
