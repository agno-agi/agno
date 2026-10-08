from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence

from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.youcom.base import DEFAULT_CRAWL_TIMEOUT_PAD, YouComReaderBase, _join_non_empty, _normalize_text
from agno.knowledge.types import ContentType


@dataclass
class YouContentsReader(YouComReaderBase):
    formats: Sequence[str] = ("markdown", "metadata")
    crawl_timeout: int = 10

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        formats: Sequence[str] = ("markdown", "metadata"),
        crawl_timeout: int = 10,
        request_timeout: Optional[float] = None,
        chunk: bool = True,
        chunk_size: int = 5000,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            request_timeout=request_timeout,
            chunk=chunk,
            chunk_size=chunk_size,
            chunking_strategy=chunking_strategy,
            name=name,
            description=description,
        )
        if not 1 <= crawl_timeout <= 60:
            raise ValueError("crawl_timeout must be between 1 and 60 seconds")
        if isinstance(formats, str):
            self.formats = tuple(part.strip() for part in formats.split(",") if part.strip())
        else:
            self.formats = tuple(formats)
        self.crawl_timeout = crawl_timeout

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        return [
            ChunkingStrategyType.CODE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        return [ContentType.URL]

    def _build_payload(self, urls: Iterable[str]) -> Dict[str, Any]:
        return {"urls": list(urls), "formats": list(self.formats)}

    def _documents_from_response(self, urls: List[str], data: Any) -> List[Document]:
        if not isinstance(data, list):
            return []
        documents: List[Document] = []
        for index, page in enumerate(data):
            if not isinstance(page, dict):
                continue
            url = page.get("url") or urls[min(index, len(urls) - 1)]
            title = page.get("title") or url
            content = _normalize_text(page.get("markdown") or page.get("html") or page.get("text"))
            if not content:
                content = ""
            meta_data = {
                "source": "youcom_contents",
                "url": url,
                "title": title,
            }
            if page.get("metadata") is not None:
                meta_data["metadata"] = page["metadata"]
            documents.extend(
                self._document_from_text(
                    doc_id=url or title,
                    name=title,
                    content=_join_non_empty([f"# {title}", f"Source: {url}" if url else "", content]),
                    meta_data=meta_data,
                )
            )
        return documents

    def read(self, urls: str | Iterable[str], name: Optional[str] = None) -> List[Document]:
        normalized_urls = self._normalize_urls(urls)
        try:
            request_timeout = self._request_timeout_or_default(self.crawl_timeout, DEFAULT_CRAWL_TIMEOUT_PAD)
            self.request_timeout = request_timeout
            data = self._json_request("POST", "/v1/contents", json_body=self._build_payload(normalized_urls))
            return self._documents_from_response(normalized_urls, data)
        except Exception as error:
            self._log_request_error("You.com contents request failed", error)
            return []

    async def async_read(self, urls: str | Iterable[str], name: Optional[str] = None) -> List[Document]:
        normalized_urls = self._normalize_urls(urls)
        try:
            request_timeout = self._request_timeout_or_default(self.crawl_timeout, DEFAULT_CRAWL_TIMEOUT_PAD)
            self.request_timeout = request_timeout
            data = await self._async_json_request("POST", "/v1/contents", json_body=self._build_payload(normalized_urls))
            return self._documents_from_response(normalized_urls, data)
        except Exception as error:
            self._log_request_error("You.com contents request failed", error)
            return []
