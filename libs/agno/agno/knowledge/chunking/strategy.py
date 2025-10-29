from abc import ABC, abstractmethod
from enum import Enum
from typing import List

from agno.knowledge.document.base import Document


class ChunkingStrategy(ABC):
    """Base class for chunking strategies"""

    @abstractmethod
    def chunk(self, document: Document) -> List[Document]:
        raise NotImplementedError

    def clean_text(self, text: str) -> str:
        """Clean the text by replacing multiple newlines with a single newline"""
        import re

        # Replace multiple newlines with a single newline
        cleaned_text = re.sub(r"\n+", "\n", text)
        # Replace multiple spaces with a single space
        cleaned_text = re.sub(r"\s+", " ", cleaned_text)
        # Replace multiple tabs with a single tab
        cleaned_text = re.sub(r"\t+", "\t", cleaned_text)
        # Replace multiple carriage returns with a single carriage return
        cleaned_text = re.sub(r"\r+", "\r", cleaned_text)
        # Replace multiple form feeds with a single form feed
        cleaned_text = re.sub(r"\f+", "\f", cleaned_text)
        # Replace multiple vertical tabs with a single vertical tab
        cleaned_text = re.sub(r"\v+", "\v", cleaned_text)

        return cleaned_text


class ChunkingStrategyType(str, Enum):
    """Enumeration of available chunking strategies."""

    AGENTIC_CHUNKER = "AgenticChunker"
    DOCUMENT_CHUNKER = "DocumentChunker"
    RECURSIVE_CHUNKER = "RecursiveChunker"
    SEMANTIC_CHUNKER = "SemanticChunker"
    FIXED_SIZE_CHUNKER = "FixedSizeChunker"
    ROW_CHUNKER = "RowChunker"
    MARKDOWN_CHUNKER = "MarkdownChunker"

    @classmethod
    def from_string(cls, strategy_name: str) -> "ChunkingStrategyType":
        """Convert a string to a ChunkingStrategyType."""
        strategy_name_clean = strategy_name.strip()

        # Try exact enum value match first
        for enum_member in cls:
            if enum_member.value == strategy_name_clean:
                return enum_member

        raise ValueError(f"Unsupported chunking strategy: {strategy_name}. Valid options: {[e.value for e in cls]}")


class ChunkingStrategyFactory:
    """Factory for creating chunking strategy instances."""

    @classmethod
    def create_strategy(cls, strategy_type: ChunkingStrategyType, **kwargs) -> ChunkingStrategy:
        """Create an instance of the chunking strategy with the given parameters."""
        strategy_map = {
            ChunkingStrategyType.AGENTIC_CHUNKER: cls._create_agentic_chunking,
            ChunkingStrategyType.DOCUMENT_CHUNKER: cls._create_document_chunking,
            ChunkingStrategyType.RECURSIVE_CHUNKER: cls._create_recursive_chunking,
            ChunkingStrategyType.SEMANTIC_CHUNKER: cls._create_semantic_chunking,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER: cls._create_fixed_chunking,
            ChunkingStrategyType.ROW_CHUNKER: cls._create_row_chunking,
            ChunkingStrategyType.MARKDOWN_CHUNKER: cls._create_markdown_chunking,
        }
        return strategy_map[strategy_type](**kwargs)

    @classmethod
    def _create_agentic_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.agentic import AgenticChunking

        # Map chunk_size to max_chunk_size for AgenticChunking
        if "chunk_size" in kwargs and "max_chunk_size" not in kwargs:
            kwargs["max_chunk_size"] = kwargs.pop("chunk_size")
        return AgenticChunking(**kwargs)

    @classmethod
    def _create_document_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.document import DocumentChunking

        return DocumentChunking(**kwargs)

    @classmethod
    def _create_recursive_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.recursive import RecursiveChunking

        return RecursiveChunking(**kwargs)

    @classmethod
    def _create_semantic_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.semantic import SemanticChunking

        return SemanticChunking(**kwargs)

    @classmethod
    def _create_fixed_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.fixed import FixedSizeChunking

        return FixedSizeChunking(**kwargs)

    @classmethod
    def _create_row_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.row import RowChunking

        # Remove chunk_size if present since RowChunking doesn't use it
        kwargs.pop("chunk_size", None)
        return RowChunking(**kwargs)

    @classmethod
    def _create_markdown_chunking(cls, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.markdown import MarkdownChunking

        return MarkdownChunking(**kwargs)
