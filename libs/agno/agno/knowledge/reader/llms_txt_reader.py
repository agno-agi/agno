import asyncio
import re
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.log import log_debug, log_error, log_warning

# Pattern to match markdown links: - [Title](url) or - [Title](url): description
# Note: titles with nested brackets (e.g. [Agent [Beta]](url)) are not supported.
_LINK_PATTERN = re.compile(r"-\s+\[([^\]]+)\]\(([^)]+)\)(?::\s*(.+))?")
# Pattern to match H2 section headers
_SECTION_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class LLMsTxtEntry:
    """A single entry parsed from an llms.txt file."""

    title: str
    url: str
    description: str
    section: str


class LLMsTxtReader(Reader):
    """Reader for llms.txt files.

    Reads an llms.txt file (see https://llmstxt.org), parses all linked documentation URLs,
    fetches the content of each linked page, and returns them as Documents.

    The llms.txt format is a standardized markdown file with:
    - An H1 heading (project name)
    - An optional blockquote summary
    - H2-delimited sections containing markdown links to documentation pages

    Example:
        reader = LLMsTxtReader(max_urls=50)
        documents = reader.read("https://docs.example.com/llms.txt")
    """

    def __init__(
        self,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        max_urls: int = 100,
        timeout: int = 30,
        proxy: Optional[str] = None,
        skip_optional: bool = False,
        **kwargs,
    ):
        if chunking_strategy is None:
            chunk_size = kwargs.get("chunk_size", 5000)
            chunking_strategy = FixedSizeChunking(chunk_size=chunk_size)
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.max_urls = max_urls
        self.timeout = timeout
        self.proxy = proxy
        self.skip_optional = skip_optional

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def parse_llms_txt(self, content: str, base_url: str) -> Tuple[str, List[LLMsTxtEntry]]:
        """Parse an llms.txt file and extract all linked URLs.

        Args:
            content: The raw text content of the llms.txt file.
            base_url: The base URL for resolving relative links.

        Returns:
            A tuple of (overview text, list of LLMsTxtEntry).
        """
        entries: List[LLMsTxtEntry] = []
        current_section = ""
        overview_lines: List[str] = []

        for line in content.split("\n"):
            section_match = _SECTION_PATTERN.match(line)
            if section_match:
                current_section = section_match.group(1).strip()
            elif not current_section:
                overview_lines.append(line)
            elif self.skip_optional and current_section.lower() == "optional":
                pass
            else:
                link_match = _LINK_PATTERN.match(line.strip())
                if link_match:
                    url = link_match.group(2).strip()
                    if not url.startswith(("http://", "https://")):
                        url = urljoin(base_url, url)
                    entries.append(
                        LLMsTxtEntry(
                            title=link_match.group(1).strip(),
                            url=url,
                            description=(link_match.group(3) or "").strip(),
                            section=current_section,
                        )
                    )

        overview = "\n".join(overview_lines).strip()
        return overview, entries

    def _process_response(self, content_type: str, text: str) -> str:
        """Classify an HTTP response by content-type and extract text."""
        if any(t in content_type for t in ["text/plain", "text/markdown"]):
            return text

        if "text/html" in content_type or text.strip().startswith(("<!DOCTYPE", "<html", "<HTML")):
            try:
                from bs4 import BeautifulSoup
            except ImportError:
                raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")

            soup = BeautifulSoup(text, "html.parser")
            for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            main = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"})
            if main:
                return main.get_text(separator="\n", strip=True)

            body = soup.find("body")
            if body:
                return body.get_text(separator="\n", strip=True)

            return soup.get_text(separator="\n", strip=True)

        return text

    def fetch_url(self, url: str) -> Optional[str]:
        """Fetch a URL and return its text content, or None on failure."""
        try:
            response = httpx.get(url, timeout=self.timeout, proxy=self.proxy, follow_redirects=True)
            response.raise_for_status()
            return self._process_response(response.headers.get("content-type", ""), response.text)
        except Exception as e:
            log_warning(f"Failed to fetch {url}: {e}")
            return None

    async def async_fetch_url(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        """Async variant of fetch_url using a shared client."""
        try:
            response = await client.get(url, timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
            return self._process_response(response.headers.get("content-type", ""), response.text)
        except Exception as e:
            log_warning(f"Failed to fetch {url}: {e}")
            return None

    def _build_documents(
        self,
        overview: str,
        entries: List[LLMsTxtEntry],
        fetched: Dict[str, str],
        llms_txt_url: str,
        name: Optional[str],
    ) -> List[Document]:
        """Build Document list from fetched content."""
        documents: List[Document] = []

        if overview:
            doc = Document(
                name=name or llms_txt_url,
                id=str(uuid.uuid4()),
                meta_data={
                    "url": llms_txt_url,
                    "type": "llms_txt_overview",
                },
                content=overview,
            )
            if self.chunk:
                documents.extend(self.chunk_document(doc))
            else:
                documents.append(doc)

        # Add each fetched page as a document
        for entry in entries:
            content = fetched.get(entry.url)
            if not content:
                continue

            doc = Document(
                name=entry.title,
                id=str(uuid.uuid4()),
                meta_data={
                    "url": entry.url,
                    "section": entry.section,
                    "description": entry.description,
                    "type": "llms_txt_linked_doc",
                },
                content=content,
            )
            if self.chunk:
                documents.extend(self.chunk_document(doc))
            else:
                documents.append(doc)

        return documents

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
        """Read an llms.txt file and all its linked documentation.

        Args:
            url: The URL of the llms.txt file.
            name: Optional name for the documents.

        Returns:
            A list of documents from the llms.txt and all linked pages.
        """
        log_debug(f"Reading llms.txt: {url}")
        llms_txt_content = self.fetch_url(url)
        if not llms_txt_content:
            log_error(f"Failed to fetch llms.txt from {url}")
            return []

        overview, entries = self.parse_llms_txt(llms_txt_content, url)
        log_debug(f"Found {len(entries)} linked URLs in llms.txt")

        entries_to_fetch = entries[: self.max_urls]
        if len(entries) > self.max_urls:
            log_warning(f"Limiting to {self.max_urls} URLs (found {len(entries)})")

        fetched: Dict[str, str] = {}
        for entry in entries_to_fetch:
            content = self.fetch_url(entry.url)
            if content:
                fetched[entry.url] = content

        log_debug(f"Successfully fetched {len(fetched)}/{len(entries_to_fetch)} linked pages")
        return self._build_documents(overview, entries_to_fetch, fetched, url, name)

    async def async_read(self, url: str, name: Optional[str] = None) -> List[Document]:
        """Asynchronously read an llms.txt file and all its linked documentation.

        Args:
            url: The URL of the llms.txt file.
            name: Optional name for the documents.

        Returns:
            A list of documents from the llms.txt and all linked pages.
        """
        log_debug(f"Reading llms.txt asynchronously: {url}")
        async with httpx.AsyncClient(proxy=self.proxy) as client:
            llms_txt_content = await self.async_fetch_url(client, url)
            if not llms_txt_content:
                log_error(f"Failed to fetch llms.txt from {url}")
                return []

            overview, entries = self.parse_llms_txt(llms_txt_content, url)
            log_debug(f"Found {len(entries)} linked URLs in llms.txt")

            entries_to_fetch = entries[: self.max_urls]
            if len(entries) > self.max_urls:
                log_warning(f"Limiting to {self.max_urls} URLs (found {len(entries)})")
            # httpx pool limits handle per-host connections, but we also cap total
            # in-flight fetches to avoid bursting 100 requests at third-party servers
            semaphore = asyncio.Semaphore(10)

            async def _fetch_entry(entry: LLMsTxtEntry) -> Tuple[str, Optional[str]]:
                async with semaphore:
                    content = await self.async_fetch_url(client, entry.url)
                    return entry.url, content

            results = await asyncio.gather(*[_fetch_entry(e) for e in entries_to_fetch])
            fetched: Dict[str, str] = {entry_url: content for entry_url, content in results if content}

            log_debug(f"Successfully fetched {len(fetched)}/{len(entries_to_fetch)} linked pages")
            return self._build_documents(overview, entries_to_fetch, fetched, url, name)
