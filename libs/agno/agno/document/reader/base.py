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
