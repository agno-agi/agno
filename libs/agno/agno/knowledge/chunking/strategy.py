import hashlib
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

from agno.knowledge.document.base import Document


class ChunkingStrategy(ABC):
    """Base class for chunking strategies"""

    @abstractmethod
    def chunk(self, document: Document) -> List[Document]:
        raise NotImplementedError

    def _generate_chunk_id(
        self, document: Document, chunk_number: int, content: Optional[str] = None, prefix: Optional[str] = None
    ) -> Optional[str]:
        """Generate a deterministic ID for the chunk."""
        suffix = f"_{prefix}_{chunk_number}" if prefix else f"_{chunk_number}"

        if document.id:
            return f"{document.id}{suffix}"
        elif document.name:
            return f"{document.name}{suffix}"
        else:
            # Hash the chunk content for a deterministic ID when no identifier exists
            hash_source = content if content else document.content
            if hash_source:
                content_hash = hashlib.md5(hash_source.encode("utf-8")).hexdigest()[:12]  # nosec B324
                return f"chunk_{content_hash}{suffix}"
            return None

    async def achunk(self, document: Document) -> List[Document]:
        """Async version of chunk. Override for truly async implementations."""
        return self.chunk(document)

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
    CODE_CHUNKER = "CodeChunker"
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
    def create_strategy(
        cls,
        strategy_type: ChunkingStrategyType,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        **kwargs,
    ) -> ChunkingStrategy:
        """Create an instance of the chunking strategy with the given parameters."""
        strategy_map = {
            ChunkingStrategyType.AGENTIC_CHUNKER: cls._create_agentic_chunking,
            ChunkingStrategyType.CODE_CHUNKER: cls._create_code_chunking,
            ChunkingStrategyType.DOCUMENT_CHUNKER: cls._create_document_chunking,
            ChunkingStrategyType.RECURSIVE_CHUNKER: cls._create_recursive_chunking,
            ChunkingStrategyType.SEMANTIC_CHUNKER: cls._create_semantic_chunking,
            ChunkingStrategyType.FIXED_SIZE_CHUNKER: cls._create_fixed_chunking,
            ChunkingStrategyType.ROW_CHUNKER: cls._create_row_chunking,
            ChunkingStrategyType.MARKDOWN_CHUNKER: cls._create_markdown_chunking,
        }
        return strategy_map[strategy_type](chunk_size=chunk_size, overlap=overlap, **kwargs)

    @classmethod
    def _create_agentic_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.agentic import AgenticChunking

        # AgenticChunking accepts max_chunk_size (not chunk_size) and no overlap
        if chunk_size is not None:
            kwargs["max_chunk_size"] = chunk_size
        # Remove overlap since AgenticChunking doesn't support it
        return AgenticChunking(**kwargs)

    @classmethod
    def _create_code_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.code import CodeChunking

        # CodeChunking accepts chunk_size but not overlap
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        # Remove overlap since CodeChunking doesn't support it
        return CodeChunking(**kwargs)

    @classmethod
    def _create_document_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.document import DocumentChunking

        # DocumentChunking accepts both chunk_size and overlap
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        if overlap is not None:
            kwargs["overlap"] = overlap
        return DocumentChunking(**kwargs)

    @classmethod
    def _create_recursive_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.recursive import RecursiveChunking

        # RecursiveChunking accepts both chunk_size and overlap
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        if overlap is not None:
            kwargs["overlap"] = overlap
        return RecursiveChunking(**kwargs)

    @classmethod
    def _create_semantic_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.semantic import SemanticChunking

        # SemanticChunking accepts chunk_size but not overlap
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        # Remove overlap since SemanticChunking doesn't support it
        return SemanticChunking(**kwargs)

    @classmethod
    def _create_fixed_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.fixed import FixedSizeChunking

        # FixedSizeChunking accepts both chunk_size and overlap
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        if overlap is not None:
            kwargs["overlap"] = overlap
        return FixedSizeChunking(**kwargs)

    @classmethod
    def _create_row_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.row import RowChunking

        # RowChunking doesn't accept chunk_size or overlap, only skip_header and clean_rows
        return RowChunking(**kwargs)

    @classmethod
    def _create_markdown_chunking(
        cls, chunk_size: Optional[int] = None, overlap: Optional[int] = None, **kwargs
    ) -> ChunkingStrategy:
        from agno.knowledge.chunking.markdown import MarkdownChunking

        # MarkdownChunking accepts both chunk_size and overlap
        if chunk_size is not None:
            kwargs["chunk_size"] = chunk_size
        if overlap is not None:
            kwargs["overlap"] = overlap
        return MarkdownChunking(**kwargs)
