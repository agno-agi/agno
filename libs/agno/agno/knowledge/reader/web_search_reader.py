import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Set
from urllib.parse import urlparse

import httpx

from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.url_reader import URLReader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, logger

try:
    from bs4 import BeautifulSoup, Tag  # noqa: F401
except ImportError:
    raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")

try:
    from ddgs import DDGS
except ImportError:
    raise ImportError("The `ddgs` package is not installed. Please install it via `pip install ddgs`.")


@dataclass
class WebSearchReader(Reader):
    """Reader that uses web search to find content for a given query"""

    search_timeout: int = 10

    request_timeout: int = 30
    delay_between_requests: float = 2.0  # Increased default delay
    max_retries: int = 3
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

    # Search engine configuration
    search_engine: Literal["duckduckgo", "google"] = "duckduckgo"
    search_delay: float = 3.0  # Delay between search requests
    max_search_retries: int = 2  # Retries for search operations

    # Rate limiting
    rate_limit_delay: float = 5.0  # Delay when rate limited
    exponential_backoff: bool = True

    # Internal state
    _visited_urls: Set[str] = field(default_factory=set)
    _url_reader: Optional[URLReader] = None
    _last_search_time: float = field(default=0.0, init=False)

    # Override default chunking strategy
    chunking_strategy: Optional[ChunkingStrategy] = SemanticChunking()

    def __post_init__(self):
        """Initialize the URL reader and chunking strategy after dataclass initialization"""
        self._url_reader = URLReader()

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for Web Search readers."""
        return [
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
            ChunkingStrategyType.SEMANTIC_CHUNKING,
            ChunkingStrategyType.FIXED_SIZE_CHUNKING,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.URL, ContentType.TEXT]

    def _respect_rate_limits(self):
        """Ensure we don't exceed rate limits"""
        current_time = time.time()
        time_since_last_search = current_time - self._last_search_time

        if time_since_last_search < self.search_delay:
            sleep_time = self.search_delay - time_since_last_search
            log_debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)

        self._last_search_time = time.time()

    def _perform_duckduckgo_search(self, query: str) -> List[Dict[str, str]]:
        """Perform web search using DuckDuckGo with rate limiting"""
        log_debug(f"Performing DuckDuckGo search for: {query}")

        for attempt in range(self.max_search_retries):
            try:
                self._respect_rate_limits()

                ddgs = DDGS(timeout=self.search_timeout)
                search_results = ddgs.text(query=query, max_results=self.max_results)

                # Convert to list and extract relevant fields
                results = []
                for result in search_results:
                    results.append(
                        {
                            "title": result.get("title", ""),
                            "url": result.get("link", ""),
                            "description": result.get("body", ""),
                        }
                    )

                log_debug(f"Found {len(results)} search results")
                return results

            except Exception as e:
                logger.warning(f"DuckDuckGo search attempt {attempt + 1} failed: {e}")
                if "rate limit" in str(e).lower() or "429" in str(e):
                    # Rate limited - wait longer
                    wait_time = (
                        self.rate_limit_delay * (2**attempt) if self.exponential_backoff else self.rate_limit_delay
                    )
                    logger.info(f"Rate limited, waiting {wait_time} seconds before retry")
                    time.sleep(wait_time)
                elif attempt < self.max_search_retries - 1:
                    # Other error - shorter wait
                    time.sleep(self.search_delay)
                else:
                    logger.error(f"All DuckDuckGo search attempts failed: {e}")
                    return []
        return []

    def _perform_google_search(self, query: str) -> List[Dict[str, str]]:
        """Perform web search using Google (requires googlesearch-python)"""
        log_debug(f"Performing Google search for: {query}")

        try:
            from googlesearch import search
        except ImportError:
            logger.error("Google search requires 'googlesearch-python'. Install with: pip install googlesearch-python")
            return []

        for attempt in range(self.max_search_retries):
            try:
                self._respect_rate_limits()

                results = []
                search_results = search(query, num_results=self.max_results, stop=self.max_results)

                for result in search_results:
                    results.append(
                        {
                            "title": getattr(result, "title", ""),
                            "url": getattr(result, "url", ""),
                            "description": getattr(result, "description", ""),
                        }
                    )

                log_debug(f"Found {len(results)} Google search results")
                return results

            except Exception as e:
                logger.warning(f"Google search attempt {attempt + 1} failed: {e}")
                if attempt < self.max_search_retries - 1:
                    time.sleep(self.search_delay)
                else:
                    logger.error(f"All Google search attempts failed: {e}")
                    return []

        return []

    def _perform_web_search(self, query: str) -> List[Dict[str, str]]:
        """Perform web search using the configured search engine"""
        if self.search_engine == "duckduckgo":
            return self._perform_duckduckgo_search(query)
        elif self.search_engine == "google":
            return self._perform_google_search(query)
        else:
            logger.error(f"Unsupported search engine: {self.search_engine}")
            return []

    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and not already visited"""
        try:
            parsed = urlparse(url)
            return bool(parsed.scheme in ["http", "https"] and parsed.netloc and url not in self._visited_urls)
        except Exception:
            return False

    def _extract_text_from_html(self, html_content: str, url: str) -> str:
        """Extract clean text content from HTML"""
        try:
            soup = BeautifulSoup(html_content, "html.parser")

            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()

            # Get text content
            text = soup.get_text()

            # Clean up whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = " ".join(chunk for chunk in chunks if chunk)

            return text

        except Exception as e:
            logger.warning(f"Error extracting text from {url}: {e}")
            return html_content

    def _fetch_url_content(self, url: str) -> Optional[str]:
        """Fetch content from a URL with retry logic"""
        headers = {"User-Agent": self.user_agent}

        for attempt in range(self.max_retries):
            try:
                response = httpx.get(url, headers=headers, timeout=self.request_timeout, follow_redirects=True)
                response.raise_for_status()

                # Check if it's HTML content
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" in content_type:
                    return self._extract_text_from_html(response.text, url)
                else:
                    # For non-HTML content, return as-is
                    return response.text

            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(random.uniform(1, 3))  # Random delay between retries
                continue

        logger.error(f"Failed to fetch content from {url} after {self.max_retries} attempts")
        return None

    def _create_document_from_url(self, url: str, content: str, search_result: Dict[str, str]) -> Document:
        """Create a Document object from URL content and search result metadata"""
        # Use the URL as the document ID
        doc_id = url

        # Use the search result title as the document name, fallback to URL
        doc_name = search_result.get("title", urlparse(url).netloc)

        # Create metadata with search information
        meta_data = {
            "url": url,
            "search_title": search_result.get("title", ""),
            "search_description": search_result.get("description", ""),
            "source": "web_search",
            "search_engine": self.search_engine,
        }

        return Document(id=doc_id, name=doc_name, content=content, meta_data=meta_data)

    def read(self, query: str) -> List[Document]:
        """Read content for a given query by performing web search and fetching content"""
        if not query:
            raise ValueError("Query cannot be empty")

        log_debug(f"Starting web search reader for query: {query}")

        # Perform web search
        search_results = self._perform_web_search(query)
        if not search_results:
            logger.warning(f"No search results found for query: {query}")
            return []

        documents: List[Document] = []

        for result in search_results:
            url = result.get("url", "")

            # Skip if URL is invalid or already visited
            if not self._is_valid_url(url):
                continue

            # Mark URL as visited
            self._visited_urls.add(url)

            # Add delay between requests to be respectful
            if len(documents) > 0:
                time.sleep(self.delay_between_requests)

            # Fetch content from URL
            content = self._fetch_url_content(url)
            if content is None:
                continue

            # Create document
            document = self._create_document_from_url(url, content, result)

            # Apply chunking if enabled
            if self.chunk:
                chunked_docs = self.chunk_document(document)
                documents.extend(chunked_docs)
            else:
                documents.append(document)

            # Stop if we've reached max_results
            if len(documents) >= self.max_results:
                break

        log_debug(f"Created {len(documents)} documents from web search")
        return documents

    async def async_read(self, query: str) -> List[Document]:
        """Asynchronously read content for a given query"""
        if not query:
            raise ValueError("Query cannot be empty")

        log_debug(f"Starting async web search reader for query: {query}")

        # Perform web search (synchronous operation)
        search_results = self._perform_web_search(query)
        if not search_results:
            logger.warning(f"No search results found for query: {query}")
            return []

        # Create tasks for fetching content from each URL
        async def fetch_url_async(result: Dict[str, str]) -> Optional[Document]:
            url = result.get("url", "")

            # Skip if URL is invalid or already visited
            if not self._is_valid_url(url):
                return None

            # Mark URL as visited
            self._visited_urls.add(url)

            try:
                # Use the URL reader for async fetching
                if self._url_reader:
                    docs = await self._url_reader.async_read(url)
                    if docs:
                        # Use the first document and add search metadata
                        doc = docs[0]
                        doc.meta_data.update(
                            {
                                "search_title": result.get("title", ""),
                                "search_description": result.get("description", ""),
                                "source": "web_search",
                                "search_engine": self.search_engine,
                            }
                        )
                        return doc

                # Fallback to manual async fetching
                headers = {"User-Agent": self.user_agent}
                async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                    response = await client.get(url, headers=headers, follow_redirects=True)
                    response.raise_for_status()

                    content_type = response.headers.get("content-type", "").lower()
                    if "text/html" in content_type:
                        content = self._extract_text_from_html(response.text, url)
                    else:
                        content = response.text

                    document = self._create_document_from_url(url, content, result)
                    return document

            except Exception as e:
                logger.warning(f"Error fetching {url}: {e}")
                return None

        # Create tasks for all URLs
        tasks = [fetch_url_async(result) for result in search_results]

        # Execute all tasks concurrently with delays
        documents = []
        for i, task in enumerate(tasks):
            if i > 0:  # Add delay between requests (except for the first one)
                await asyncio.sleep(self.delay_between_requests)

            doc = await task
            if doc is not None:
                # Apply chunking if enabled
                if self.chunk:
                    chunked_docs = await self.chunk_documents_async([doc])
                    documents.extend(chunked_docs)
                else:
                    documents.append(doc)

                # Stop if we've reached max_results
                if len(documents) >= self.max_results:
                    break

        log_debug(f"Created {len(documents)} documents from async web search")
        return documents
