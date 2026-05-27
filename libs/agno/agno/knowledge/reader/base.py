import asyncio
from dataclasses import dataclass, field
from typing import Any, List, Optional

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyFactory, ChunkingStrategyType
from agno.knowledge.document.base import Document
from agno.knowledge.types import ContentType


@dataclass
class Reader:
    """Base class for reading documents"""

    chunk: bool = True
    chunk_size: int = 5000
    separators: List[str] = field(default_factory=lambda: ["\n", "\n\n", "\r", "\r\n", "\n\r", "\t", " ", "  "])
    chunking_strategy: Optional[ChunkingStrategy] = None
    name: Optional[str] = None
    description: Optional[str] = None
    max_results: int = 5  # Maximum number of results to return (useful for search-based readers)
    encoding: Optional[str] = None

    def __init__(
        self,
        chunk: bool = True,
        chunk_size: int = 5000,
        separators: Optional[List[str]] = None,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        max_results: int = 5,
        encoding: Optional[str] = None,
        **kwargs,
    ) -> None:
        self.chunk = chunk
        self.chunk_size = chunk_size
        self.separators = (
            separators if separators is not None else ["\n", "\n\n", "\r", "\r\n", "\n\r", "\t", " ", "  "]
        )
        self.chunking_strategy = chunking_strategy
        self.name = name
        self.description = description
        self.max_results = max_results
        self.encoding = encoding

    def set_chunking_strategy_from_string(
        self, strategy_name: str, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> None:
        """Set the chunking strategy from a string name."""
        try:
            strategy_type = ChunkingStrategyType.from_string(strategy_name)
            self.chunking_strategy = ChunkingStrategyFactory.create_strategy(
                strategy_type, chunk_size=chunk_size, overlap=overlap, **kwargs
            )
        except ValueError as e:
            raise ValueError(f"Failed to set chunking strategy: {e}")

    def read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        raise NotImplementedError

    async def async_read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        raise NotImplementedError

    @classmethod
    def get_supported_chunking_strategies(cls) -> List[ChunkingStrategyType]:
        raise NotImplementedError

    @classmethod
    def get_supported_content_types(cls) -> List[ContentType]:
        raise NotImplementedError

    def chunk_document(self, document: Document) -> List[Document]:
        if self.chunking_strategy is None:
            self.chunking_strategy = FixedSizeChunking(chunk_size=self.chunk_size)
        return self.chunking_strategy.chunk(document)

    async def achunk_document(self, document: Document) -> List[Document]:
        """Async version of chunk_document."""
        if self.chunking_strategy is None:
            self.chunking_strategy = FixedSizeChunking(chunk_size=self.chunk_size)
        return await self.chunking_strategy.achunk(document)

    async def chunk_documents_async(self, documents: List[Document]) -> List[Document]:
        """
        Asynchronously chunk a list of documents.

        Args:
            documents: List of documents to be chunked.

        Returns:
            A flattened list of chunked documents.
        """
        # Process chunking in parallel for all documents
        chunked_lists = await asyncio.gather(*[self.achunk_document(doc) for doc in documents])
        # Flatten the result
        return [chunk for sublist in chunked_lists for chunk in sublist]
