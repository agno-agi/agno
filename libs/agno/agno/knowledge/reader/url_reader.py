from io import BytesIO
from os.path import basename
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.reader.csv_reader import CSVReader
from agno.knowledge.reader.pdf_reader import PDFReader
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
            ChunkingStrategyType.FIXED_SIZE_CHUNKER,
            ChunkingStrategyType.AGENTIC_CHUNKER,
            ChunkingStrategyType.DOCUMENT_CHUNKER,
            ChunkingStrategyType.RECURSIVE_CHUNKER,
            ChunkingStrategyType.SEMANTIC_CHUNKER,
        ]

    @classmethod
    def get_supported_content_types(self) -> List[ContentType]:
        return [ContentType.URL]

    def read(
        self, url: str, id: Optional[str] = None, name: Optional[str] = None, password: Optional[str] = None
    ) -> List[Document]:
        if not url:
            raise ValueError("No url provided")

        log_debug(f"Reading: {url}")

        # Retry the request up to 3 times with exponential backoff
        response = fetch_with_retry(url, proxy=self.proxy)

        documents = self._create_documents(
            url=url, text=response.text, content=response.content, id=id, name=name, password=password
        )

        if not self.chunk:
            return documents

        chunked_documents = []
        for document in documents:
            chunked_documents.append(self.chunk_document(document))
        return [doc for sublist in chunked_documents for doc in sublist]

    async def async_read(
        self, url: str, id: Optional[str] = None, name: Optional[str] = None, password: Optional[str] = None
    ) -> List[Document]:
        """Async version of read method"""
        if not url:
            raise ValueError("No url provided")

        log_debug(f"Reading async: {url}")
        client_args = {"proxy": self.proxy} if self.proxy else {}
        async with httpx.AsyncClient(**client_args) as client:  # type: ignore
            response = await async_fetch_with_retry(url, client=client)

        documents = self._create_documents(
            url=url, text=response.text, content=response.content, id=id, name=name, password=password
        )

        if not self.chunk:
            return documents

        return await self.chunk_documents_async(documents)

    def _create_documents(
        self,
        url: str,
        text: str,
        content: bytes,
        id: Optional[str] = None,
        name: Optional[str] = None,
        password: Optional[str] = None,
    ) -> List[Document]:
        """Helper method to create a document from URL content"""

        # Determine file extension from URL
        parsed_url = urlparse(url)
        url_path = Path(parsed_url.path)  # type: ignore
        file_extension = url_path.suffix.lower()

        # Read the document using the appropriate reader
        if file_extension == ".csv":
            filename = basename(parsed_url.path) or "data.csv"
            return CSVReader().read(file=BytesIO(content), name=filename)
        elif file_extension == ".pdf":
            if password:
                return PDFReader().read(pdf=BytesIO(content), name=name, password=password)
            else:
                return PDFReader().read(pdf=BytesIO(content), name=name)
        else:
            doc_name = name or parsed_url.path.strip("/").replace("/", "_").replace(" ", "_")
            if not doc_name:
                doc_name = parsed_url.netloc
            if not doc_name:
                doc_name = url

        return [
            Document(
                name=doc_name,
                id=id or doc_name,
                meta_data={"url": url},
                content=text,
                size=len(text),
            )
        ]
