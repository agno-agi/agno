from typing import List, Optional
from urllib.parse import urlparse

import httpx

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.utils.http import async_fetch_with_retry, fetch_with_retry
from agno.utils.log import log_debug


class URLReader(Reader):
    """Reader for general URL content"""

    def __init__(
        self, chunking_strategy: Optional[ChunkingStrategy] = FixedSizeChunking(), proxy: Optional[str] = None, **kwargs
    ):
        super().__init__(chunking_strategy=chunking_strategy, **kwargs)
        self.proxy = proxy

    @classmethod
    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for URL readers."""
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKING,
            ChunkingStrategyType.AGENTIC_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
            ChunkingStrategyType.SEMANTIC_CHUNKING,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.URL]

    def read(self, url: str, id: Optional[str] = None, name: Optional[str] = None) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        log_debug(f"Reading: {url}")
        # Retry the request up to 3 times with exponential backoff
        response = fetch_with_retry(url, proxy=self.proxy)

        document = self._create_document(url, response.text, id, name)
        if self.chunk:
            return self.chunk_document(document)
        return [document]

    async def async_read(self, url: str, id: Optional[str] = None, name: Optional[str] = None) -> List[Document]:
        """Async version of read method"""
        if not url:
            raise ValueError("No url provided")

        log_debug(f"Reading async: {url}")
        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await async_fetch_with_retry(url, client=client)

        document = self._create_document(url, response.text, id, name)
        if self.chunk:
            return await self.chunk_documents_async([document])
        return [document]

    def _create_document(
        self, url: str, content: str, id: Optional[str] = None, name: Optional[str] = None
    ) -> Document:
        """Helper method to create a document from URL content"""
        parsed_url = urlparse(url)
        doc_name = name or parsed_url.path.strip("/").replace("/", "_").replace(" ", "_")
        if not doc_name:
            doc_name = parsed_url.netloc
        if not doc_name:
            doc_name = url

        return Document(
            name=doc_name,
            id=id or doc_name,
            meta_data={"url": url},
            content=content,
            size=len(content),
        )
