import asyncio
from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, Union

from pydantic import model_validator

from agno.document import Document
from agno.document.reader.browser_website_reader import BrowserWebsiteReader
from agno.document.reader.website_reader import WebsiteReader
from agno.knowledge.agent import AgentKnowledge
from agno.utils.log import log_debug, log_info, logger


class WebsiteKnowledgeBase(AgentKnowledge):
    urls: List[str] = []
    reader: Optional[Union[WebsiteReader, BrowserWebsiteReader]] = None
    reader_type: str = "http"  # "http" for WebsiteReader, "browser" for BrowserWebsiteReader

    # Common parameters for both readers
    max_depth: int = 3
    max_links: int = 10

    # BrowserWebsiteReader specific parameters
    browser_type: str = "chromium"  # chromium, firefox, webkit
    headless: bool = True
    user_agent: Optional[str] = None
    proxy: Optional[Union[str, Dict[str, str]]] = None  # String for http proxy, Dict for browser proxy
    timeout: int = 10  # seconds for http, will be converted to ms for browser
    wait_for_load_state: str = "domcontentloaded"
    viewport_size: Optional[Dict[str, int]] = None
    extra_wait_time: float = 0

    @model_validator(mode="after")
    def set_reader(self) -> "WebsiteKnowledgeBase":
        if self.reader is None:
            if self.reader_type.lower() == "browser":
                # Convert proxy format for browser reader
                browser_proxy = None
                if self.proxy:
                    if isinstance(self.proxy, str):
                        # Convert string proxy to dict format for Playwright
                        browser_proxy = {"server": self.proxy}
                    else:
                        browser_proxy = self.proxy

                self.reader = BrowserWebsiteReader(
                    max_depth=self.max_depth,
                    max_links=self.max_links,
                    browser_type=self.browser_type,
                    headless=self.headless,
                    user_agent=self.user_agent,
                    proxy=browser_proxy,
                    timeout=self.timeout * 1000,  # Convert to milliseconds
                    wait_for_load_state=self.wait_for_load_state,
                    viewport_size=self.viewport_size,
                    extra_wait_time=self.extra_wait_time,
                    chunking_strategy=self.chunking_strategy,
                )
            else:  # Default to http reader
                # Convert proxy format for http reader
                http_proxy = None
                if self.proxy:
                    if isinstance(self.proxy, dict):
                        # Use the server value if it's a dict
                        http_proxy = self.proxy.get("server")
                    else:
                        http_proxy = self.proxy

                self.reader = WebsiteReader(
                    max_depth=self.max_depth,
                    max_links=self.max_links,
                    timeout=self.timeout,
                    proxy=http_proxy,
                    chunking_strategy=self.chunking_strategy,
                )
        return self

    @property
    def document_lists(self) -> Iterator[List[Document]]:
        """Iterate over urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            Iterator[List[Document]]: Iterator yielding list of documents
        """
        if self.reader is not None:
            for _url in self.urls:
                yield self.reader.read(url=_url)

    @property
    async def async_document_lists(self) -> AsyncIterator[List[Document]]:
        """Asynchronously iterate over urls and yield lists of documents.
        Each object yielded by the iterator is a list of documents.

        Returns:
            AsyncIterator[List[Document]]: AsyncIterator yielding list of documents
        """
        if self.reader is not None:
            for _url in self.urls:
                yield await self.reader.async_read(url=_url)

    def load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Load the website contents to the vector db"""

        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if self.reader is None:
            logger.warning("No reader provided")
            return

        if recreate:
            log_debug("Dropping collection")
            self.vector_db.drop()

        log_debug("Creating collection")
        self.vector_db.create()

        log_info(f"Loading knowledge base using {self.reader_type} reader")

        # Given that the crawler needs to parse the URL before existence can be checked
        # We check if the website url exists in the vector db if recreate is False
        urls_to_read = self.urls.copy()
        if not recreate:
            for url in urls_to_read:
                log_debug(f"Checking if {url} exists in the vector db")
                if self.vector_db.name_exists(name=url):
                    log_debug(f"Skipping {url} as it exists in the vector db")
                    urls_to_read.remove(url)

        num_documents = 0
        for url in urls_to_read:
            try:
                if document_list := self.reader.read(url=url):
                    # Filter out documents which already exist in the vector db
                    if not recreate:
                        document_list = [
                            document for document in document_list if not self.vector_db.doc_exists(document)
                        ]
                        if not document_list:
                            continue
                    if upsert and self.vector_db.upsert_available():
                        self.vector_db.upsert(documents=document_list, filters=filters)
                    else:
                        self.vector_db.insert(documents=document_list, filters=filters)
                    num_documents += len(document_list)
                    log_info(f"Loaded {num_documents} documents to knowledge base")
            except Exception as e:
                logger.error(f"Failed to load URL {url}: {e}")
                # Continue with other URLs even if one fails

        if self.optimize_on is not None and num_documents > self.optimize_on:
            log_debug("Optimizing Vector DB")
            self.vector_db.optimize()

    async def async_load(
        self,
        recreate: bool = False,
        upsert: bool = True,
        skip_existing: bool = True,
        filters: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Asynchronously load the website contents to the vector db"""

        if self.vector_db is None:
            logger.warning("No vector db provided")
            return

        if self.reader is None:
            logger.warning("No reader provided")
            return

        vector_db = self.vector_db
        reader = self.reader

        if recreate:
            log_debug("Dropping collection asynchronously")
            await vector_db.async_drop()

        log_debug("Creating collection asynchronously")
        await vector_db.async_create()

        log_info(f"Loading knowledge base asynchronously using {self.reader_type} reader")
        num_documents = 0

        urls_to_read = self.urls.copy()
        if not recreate:
            for url in urls_to_read[:]:
                log_debug(f"Checking if {url} exists in the vector db")
                name_exists = vector_db.async_name_exists(name=url)
                if name_exists:
                    log_debug(f"Skipping {url} as it exists in the vector db")
                    urls_to_read.remove(url)

        async def process_url(url: str) -> List[Document]:
            try:
                document_list = await reader.async_read(url=url)

                if not recreate:
                    filtered_documents = []
                    for document in document_list:
                        if not await vector_db.async_doc_exists(document):
                            filtered_documents.append(document)
                    document_list = filtered_documents

                return document_list
            except Exception as e:
                logger.error(f"Error processing URL {url}: {e}")
                return []

        url_tasks = [process_url(url) for url in urls_to_read]
        all_document_lists = await asyncio.gather(*url_tasks)

        for document_list in all_document_lists:
            if document_list:
                if upsert and vector_db.upsert_available():
                    await vector_db.async_upsert(documents=document_list, filters=filters)
                else:
                    await vector_db.async_insert(documents=document_list, filters=filters)
                num_documents += len(document_list)
                log_info(f"Loaded {num_documents} documents to knowledge base asynchronously")

        if self.optimize_on is not None and num_documents > self.optimize_on:
            log_debug("Optimizing Vector DB")
            vector_db.optimize()

    def configure_browser_reader(
        self,
        browser_type: str = "chromium",
        headless: bool = True,
        user_agent: Optional[str] = None,
        proxy: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        wait_for_load_state: str = "domcontentloaded",
        viewport_size: Optional[Dict[str, int]] = None,
        extra_wait_time: float = 0,
    ) -> None:
        """
        Configure browser-specific settings for the BrowserWebsiteReader.

        Args:
            browser_type: Browser to use ('chromium', 'firefox', 'webkit')
            headless: Whether to run browser in headless mode
            user_agent: Custom user agent string
            proxy: Proxy configuration dict with 'server' key
            timeout: Timeout in seconds
            wait_for_load_state: When to consider page loaded
            viewport_size: Browser viewport size
            extra_wait_time: Additional wait time after page load
        """
        self.browser_type = browser_type
        self.headless = headless
        self.user_agent = user_agent
        self.proxy = proxy
        self.timeout = timeout
        self.wait_for_load_state = wait_for_load_state
        self.viewport_size = viewport_size
        self.extra_wait_time = extra_wait_time

        # Reset reader to apply new configuration
        self.reader = None
        self.set_reader()

    def use_browser_reader(self, **browser_config) -> None:
        """
        Switch to using BrowserWebsiteReader with optional configuration.

        Args:
            **browser_config: Browser configuration parameters
        """
        self.reader_type = "browser"
        if browser_config:
            self.configure_browser_reader(**browser_config)
        else:
            # Reset reader to apply new reader type
            self.reader = None
            self.set_reader()

    def use_http_reader(self) -> None:
        """Switch to using the standard HTTP-based WebsiteReader."""
        self.reader_type = "http"
        # Reset reader to apply new reader type
        self.reader = None
        self.set_reader()
