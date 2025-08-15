import asyncio
from dataclasses import dataclass, field
from typing import Any, List, Optional

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy, ChunkingStrategyType
from agno.knowledge.document.base import Document


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

    def __init__(
        self,
        chunk: bool = True,
        chunk_size: int = 5000,
        separators: Optional[List[str]] = None,
        chunking_strategy: Optional[ChunkingStrategy] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        max_results: int = 5,
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

    def set_chunking_strategy_from_string(self, strategy_name: str, **kwargs) -> None:
        """Set the chunking strategy from a string name."""
        try:
            strategy_type = ChunkingStrategyType.from_string(strategy_name)
            self.chunking_strategy = strategy_type.create_strategy(**kwargs)
        except ValueError as e:
            raise ValueError(f"Failed to set chunking strategy: {e}")

    def set_chunking_strategy(self, strategy_type: ChunkingStrategyType, **kwargs) -> None:
        """Set the chunking strategy from a ChunkingStrategyType enum."""
        self.chunking_strategy = strategy_type.create_strategy(**kwargs)

    def read(self, obj: Any, name: Optional[str] = None) -> List[Document]:
        raise NotImplementedError

    async def async_read(self, obj: Any, name: Optional[str] = None, password: Optional[str] = None) -> List[Document]:
        raise NotImplementedError

    def get_supported_chunking_strategies(self) -> List[ChunkingStrategyType]:
        """Get the list of supported chunking strategies for this reader.

        Returns:
            List of ChunkingStrategyType enums that this reader supports.
        """
        # Default implementation returns common strategies
        return [
            ChunkingStrategyType.FIXED_SIZE_CHUNKING,
            ChunkingStrategyType.DOCUMENT_CHUNKING,
            ChunkingStrategyType.RECURSIVE_CHUNKING,
        ]

    def chunk_document(self, document: Document) -> List[Document]:
        print(f"chunk_document: {self.chunking_strategy}")
        if self.chunking_strategy is None:
            self.chunking_strategy = FixedSizeChunking(chunk_size=self.chunk_size)
        return self.chunking_strategy.chunk(document)  # type: ignore

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
