"""Chunking strategies for splitting documents into smaller pieces for vector storage.

This module provides the base class and factory for all chunking strategies. The key
innovation is the unified ID generation system that ensures all chunks have valid,
deterministic IDs even when source documents lack explicit identifiers.

ID Generation Fallback (implemented in _generate_chunk_id):
    1. document.id   - Use if available (e.g., "doc123_1", "doc123_2")
    2. document.name - Fallback if id is None (e.g., "my_file_1", "my_file_2")
    3. content hash  - Final fallback using MD5 (e.g., "chunk_a3f2b8c9d1e4_1")

This three-tier approach solves a critical bug where documents from APIs (which often
lack explicit IDs) would produce chunks with id=None, causing database insert failures.

Example:
    >>> from agno.knowledge.chunking.fixed import FixedSizeChunking
    >>> from agno.knowledge.document.base import Document
    >>> doc = Document(content="Hello world")  # No id or name
    >>> chunker = FixedSizeChunking(chunk_size=5)
    >>> chunks = chunker.chunk(doc)
    >>> chunks[0].id  # Returns "chunk_3e25960a79d_1" (hash-based)
"""

import hashlib
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

from agno.knowledge.document.base import Document


class ChunkingStrategy(ABC):
    """Base class for all chunking strategies.

    All chunking strategies inherit from this class and get access to:
    - _generate_chunk_id(): Unified ID generation with fallback logic
    - clean_text(): Text normalization that preserves paragraph structure

    Subclasses must implement the chunk() method to define their splitting logic.
    """

    @abstractmethod
    def chunk(self, document: Document) -> List[Document]:
        raise NotImplementedError

    def _generate_chunk_id(self, document: Document, chunk_number: int, content: Optional[str] = None) -> str:
        """Generate a unique, deterministic chunk ID.

        This method implements a three-tier fallback strategy to ensure every chunk
        gets a valid ID, which is required for database storage. Without this, documents
        created from API responses or programmatically (without explicit IDs) would
        fail to insert into vector databases.

        Fallback order:
            1. document.id   -> "{document.id}_{chunk_number}"
            2. document.name -> "{document.name}_{chunk_number}"
            3. content hash  -> "chunk_{md5_hash[:12]}_{chunk_number}"

        The hash-based fallback is deterministic: the same content always produces
        the same ID. This enables idempotent upserts and reproducible results.

        Args:
            document: The source document being chunked
            chunk_number: The 1-based index of this chunk (e.g., 1, 2, 3...)
            content: Optional chunk content to hash. If provided, hashes the chunk
                     instead of the full document, giving more granular IDs.

        Returns:
            A non-None string ID like "doc123_1" or "chunk_a3f2b8c9d1e4_1"
        """
        if document.id:
            return f"{document.id}_{chunk_number}"
        elif document.name:
            return f"{document.name}_{chunk_number}"
        else:
            # Generate a deterministic ID from content hash
            hash_source = content if content else document.content
            content_hash = hashlib.md5(hash_source.encode()).hexdigest()[:12]
            return f"chunk_{content_hash}_{chunk_number}"

    def clean_text(self, text: str) -> str:
        """Clean the text by normalizing whitespace while preserving paragraph structure.

        Bug fix: The previous implementation used r"\\s+" which matches ALL whitespace
        including newlines. This destroyed paragraph breaks (e.g., "Hello\\n\\nWorld"
        became "Hello World"). Now using character classes that exclude newlines.
        """
        import re

        # Normalize line endings to \n first
        cleaned_text = re.sub(r"\r\n", "\n", text)
        cleaned_text = re.sub(r"\r", "\n", cleaned_text)

        # Preserve paragraph breaks: 3+ newlines → 2 newlines (paragraph break)
        cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

        # Replace multiple horizontal whitespace (spaces/tabs) with single space
        # Bug fix: Using [ \t]+ instead of \s+ to avoid destroying newlines
        cleaned_text = re.sub(r"[ \t]+", " ", cleaned_text)

        # Clean up spaces around newlines (but preserve the newlines)
        cleaned_text = re.sub(r" *\n *", "\n", cleaned_text)

        # Strip leading/trailing whitespace from the entire text
        cleaned_text = cleaned_text.strip()

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
