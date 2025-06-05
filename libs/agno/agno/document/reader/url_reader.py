from typing import List, Optional
from urllib.parse import urlparse

import httpx

from agno.document.base import Document
from agno.document.reader.base import Reader
from agno.utils.http import async_fetch_with_retry, fetch_with_retry
from agno.utils.log import log_debug


class URLReader(Reader):
    """Reader for general URL content"""

    def __init__(self, proxy: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.proxy = proxy

    def read(self, url: str) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        log_debug(f"Reading: {url}")
        # Retry the request up to 3 times with exponential backoff
        response = fetch_with_retry(url, proxy=self.proxy)

        document = self._create_document(url, response.text)
        if self.chunk:
            return self.chunk_document(document)
        return [document]

    async def async_read(self, url: str) -> List[Document]:
        """Async version of read method"""
        if not url:
            raise ValueError("No url provided")

        log_debug(f"Reading async: {url}")
        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await async_fetch_with_retry(url, client=client)

        document = self._create_document(url, response.text)
        if self.chunk:
            return await self.chunk_documents_async([document])
        return [document]

    def _create_document(self, url: str, content: str) -> Document:
        """Helper method to create a document from URL content"""
        parsed_url = urlparse(url)
        doc_name = parsed_url.path.strip("/").replace("/", "_").replace(" ", "_")
        if not doc_name:
            doc_name = parsed_url.netloc

        return Document(
            name=doc_name,
            id=doc_name,
            meta_data={"url": url},
            content=content,
        )
