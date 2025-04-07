import asyncio
from dataclasses import dataclass, field
from typing import Any, List

from agno.document.base import Document
from agno.document.chunking.fixed import FixedSizeChunking
from agno.document.chunking.strategy import ChunkingStrategy


@dataclass
class Reader:
    """Base class for reading documents"""

    chunk: bool = True
    chunk_size: int = 3000
    separators: List[str] = field(default_factory=lambda: ["\n", "\n\n", "\r", "\r\n", "\n\r", "\t", " ", "  "])
    chunking_strategy: ChunkingStrategy = field(default_factory=FixedSizeChunking)

    def read(self, obj: Any) -> List[Document]:
        raise NotImplementedError

    async def async_read(self, obj: Any) -> List[Document]:
        raise NotImplementedError

    def chunk_document(self, document: Document) -> List[Document]:
        return self.chunking_strategy.chunk(document)

    async def chunk_documents_async(self, documents: List[Document]) -> List[Document]:
        """
        Asynchronously chunk a list of documents using the instance's chunk_document method.

        Args:
            documents: List of documents to be chunked.

        Returns:
            A flattened list of chunked documents.
        """

        async def _chunk_document_async(doc: Document) -> List[Document]:
            return await asyncio.to_thread(self.chunk_document, doc)

        # Process chunking in parallel for all documents
        chunked_lists = await asyncio.gather(*[_chunk_document_async(doc) for doc in documents])
        # Flatten the result
        return [chunk for sublist in chunked_lists for chunk in sublist]
