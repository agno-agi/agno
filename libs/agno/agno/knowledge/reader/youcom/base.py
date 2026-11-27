import hashlib
import json
from dataclasses import dataclass
from os import getenv
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

from agno.knowledge.chunking.semantic import SemanticChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.utils.log import log_error, log_warning, logger

DEFAULT_BASE_URL = "https://ydc-index.io"
DEFAULT_REQUEST_TIMEOUT = 30
DEFAULT_CRAWL_TIMEOUT_PAD = 10


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)


def _join_non_empty(parts: Sequence[str]) -> str:
    return "\n\n".join(part for part in parts if part)


def _slug(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


@dataclass
class YouComReaderBase(Reader):
    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    request_timeout: Optional[float] = None

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        request_timeout: Optional[float] = None,
        chunk: bool = True,
        chunk_size: int = 5000,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> None:
        if chunking_strategy is None:
            try:
                chunking_strategy = SemanticChunking(chunk_size=chunk_size)
            except Exception:
                chunking_strategy = None

        super().__init__(chunk=chunk, chunk_size=chunk_size, chunking_strategy=chunking_strategy, name=name, description=description)

        self.api_key = api_key or getenv("YDC_API_KEY")
        if not self.api_key:
            log_error("YDC_API_KEY not set. Please set the YDC_API_KEY environment variable.")
        self.base_url = (base_url or getenv("YDC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.request_timeout = request_timeout

    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key or "", "Accept": "application/json"}

    def _chunk_document(self, document: Document) -> List[Document]:
        if self.chunk:
            return self.chunk_document(document)
        return [document]

    def _maybe_chunk_document(self, document: Document) -> List[Document]:
        if document.content and self.chunk:
            return self.chunk_document(document)
        return [document]

    def _request_timeout_or_default(self, crawl_timeout: int, pad: int = DEFAULT_CRAWL_TIMEOUT_PAD) -> Optional[float]:
        if self.request_timeout is not None:
            return self.request_timeout
        return max(DEFAULT_REQUEST_TIMEOUT, crawl_timeout + pad)

    def _ensure_query(self, query: str) -> str:
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        return query.strip()

    def _normalize_urls(self, urls: str | Iterable[str]) -> List[str]:
        if isinstance(urls, str):
            normalized = [urls]
        else:
            normalized = [url for url in urls if url]
        if not normalized:
            raise ValueError("At least one URL is required")
        return normalized

    def _json_request(self, method: str, path: str, *, params: Optional[Dict[str, Any]] = None, json_body: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url}{path}"
        with httpx.Client(timeout=self.request_timeout) as client:
            response = client.request(method, url, headers=self._headers(), params=params, json=json_body)
        response.raise_for_status()
        return response.json()

    async def _async_json_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.request(method, url, headers=self._headers(), params=params, json=json_body)
        response.raise_for_status()
        return response.json()

    def _document_from_text(self, *, doc_id: str, name: str, content: str, meta_data: Dict[str, Any]) -> List[Document]:
        document = Document(id=doc_id, name=name, content=content, meta_data=meta_data)
        return self._maybe_chunk_document(document)

    def _log_request_error(self, prefix: str, error: Exception) -> None:
        log_warning(f"{prefix}: {error}")
        logger.exception(prefix)
