import asyncio
import re
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

try:
    from bs4 import BeautifulSoup  # noqa: F401
except ImportError:
    raise ImportError("The `bs4` package is not installed. Please install it via `pip install beautifulsoup4`.")

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.http import async_fetch_with_retry, fetch_with_retry
from agno.utils.log import log_debug, log_error, log_warning

_LINK_PATTERN = re.compile(r"-\s+\[([^\]]+)\]\(([^)]+)\)(?::\s*(.+))?")
_SECTION_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)


@dataclass
class LLMsTxtEntry:
    title: str
    url: str
    description: str
    section: str


class LLMsTxtReader(Reader):
    """Reader for llms.txt files (see https://llmstxt.org).

    Example:
        reader = LLMsTxtReader(max_urls=20)
        documents = reader.read("https://docs.example.com/llms.txt")
    """

    def __init__(
        self,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        max_urls: int = 20,
        timeout: int = 60,
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

    # Helpers

    def _process_response(self, content_type: str, text: str) -> str:
        if any(t in content_type for t in ["text/plain", "text/markdown"]):
            return text

        if "text/html" in content_type or text.strip().startswith(("<!DOCTYPE", "<html", "<HTML")):
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

    def _build_documents(
        self,
        overview: str,
        entries: List[LLMsTxtEntry],
        fetched: Dict[str, str],
        llms_txt_url: str,
        name: Optional[str],
    ) -> List[Document]:
        documents: List[Document] = []

        if overview:
            doc = Document(
                name=name or llms_txt_url,
                id=str(uuid.uuid4()),
                meta_data={"url": llms_txt_url, "type": "llms_txt_overview"},
                content=overview,
            )
            if self.chunk:
                documents.extend(self.chunk_document(doc))
            else:
                documents.append(doc)

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

    # Public methods

    def parse_llms_txt(self, content: str, base_url: str) -> Tuple[str, List[LLMsTxtEntry]]:
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

    def fetch_url(self, url: str) -> Optional[str]:
        try:
            response = fetch_with_retry(
                url, max_retries=1, proxy=self.proxy, timeout=self.timeout, follow_redirects=True
            )
            return self._process_response(response.headers.get("content-type", ""), response.text)
        except Exception as e:
            log_warning(f"Failed to fetch {url}: {e}")
            return None

    async def async_fetch_url(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        try:
            response = await async_fetch_with_retry(
                url, client=client, max_retries=1, timeout=self.timeout, follow_redirects=True
            )
            return self._process_response(response.headers.get("content-type", ""), response.text)
        except Exception as e:
            log_warning(f"Failed to fetch {url}: {e}")
            return None

    def read(self, url: str, name: Optional[str] = None) -> List[Document]:
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

            # httpx AsyncClient limits concurrent connections per host (default 20)
            async def _fetch_entry(entry: LLMsTxtEntry) -> Tuple[str, Optional[str]]:
                content = await self.async_fetch_url(client, entry.url)
                return entry.url, content

            results = await asyncio.gather(*[_fetch_entry(e) for e in entries_to_fetch])
            fetched: Dict[str, str] = {entry_url: content for entry_url, content in results if content}

            log_debug(f"Successfully fetched {len(fetched)}/{len(entries_to_fetch)} linked pages")
            return self._build_documents(overview, entries_to_fetch, fetched, url, name)
