from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List

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


class ChunkingStrategyType(Enum):
    """Enumeration of available chunking strategies."""

    AGENTIC_CHUNKING = "AgenticChunking"
    DOCUMENT_CHUNKING = "DocumentChunking"
    RECURSIVE_CHUNKING = "RecursiveChunking"
    SEMANTIC_CHUNKING = "SemanticChunking"
    FIXED_SIZE_CHUNKING = "FixedSizeChunking"
    ROW_CHUNKING = "RowChunking"
    MARKDOWN_CHUNKING = "MarkdownChunking"

    def create_strategy(self, **kwargs) -> ChunkingStrategy:
        """Create an instance of the chunking strategy with the given parameters."""
        strategy_map: Dict[ChunkingStrategyType, callable] = {
            ChunkingStrategyType.AGENTIC_CHUNKING: self._create_agentic_chunking,
            ChunkingStrategyType.DOCUMENT_CHUNKING: self._create_document_chunking,
            ChunkingStrategyType.RECURSIVE_CHUNKING: self._create_recursive_chunking,
            ChunkingStrategyType.SEMANTIC_CHUNKING: self._create_semantic_chunking,
            ChunkingStrategyType.FIXED_SIZE_CHUNKING: self._create_fixed_chunking,
            ChunkingStrategyType.ROW_CHUNKING: self._create_row_chunking,
            ChunkingStrategyType.MARKDOWN_CHUNKING: self._create_markdown_chunking,
        }
        return strategy_map[self](**kwargs)

    def _create_agentic_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.agentic import AgenticChunking

        # Map chunk_size to max_chunk_size for AgenticChunking
        if "chunk_size" in kwargs and "max_chunk_size" not in kwargs:
            kwargs["max_chunk_size"] = kwargs.pop("chunk_size")
        return AgenticChunking(**kwargs)

    def _create_document_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.document import DocumentChunking

        return DocumentChunking(**kwargs)

    def _create_recursive_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.recursive import RecursiveChunking

        return RecursiveChunking(**kwargs)

    def _create_semantic_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.semantic import SemanticChunking

        return SemanticChunking(**kwargs)

    def _create_fixed_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.fixed import FixedSizeChunking

        return FixedSizeChunking(**kwargs)

    def _create_row_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.row import RowChunking

        # Remove chunk_size if present since RowChunking doesn't use it
        kwargs.pop("chunk_size", None)
        return RowChunking(**kwargs)

    def _create_markdown_chunking(self, **kwargs) -> ChunkingStrategy:
        from agno.knowledge.chunking.markdown import MarkdownChunking

        return MarkdownChunking(**kwargs)

    @classmethod
    def from_string(cls, strategy_name: str) -> "ChunkingStrategyType":
        """Convert a string to a ChunkingStrategyType enum."""
        strategy_name_lower = strategy_name.lower().strip()

        # Map various string representations to enum values
        string_mapping = {
            "agentic": cls.AGENTIC_CHUNKING,
            "agenticchunking": cls.AGENTIC_CHUNKING,
            "document": cls.DOCUMENT_CHUNKING,
            "documentchunking": cls.DOCUMENT_CHUNKING,
            "recursive": cls.RECURSIVE_CHUNKING,
            "recursivechunking": cls.RECURSIVE_CHUNKING,
            "semantic": cls.SEMANTIC_CHUNKING,
            "semanticchunking": cls.SEMANTIC_CHUNKING,
            "fixed": cls.FIXED_SIZE_CHUNKING,
            "fixedsize": cls.FIXED_SIZE_CHUNKING,
            "fixedsizechunking": cls.FIXED_SIZE_CHUNKING,
            "row": cls.ROW_CHUNKING,
            "rowchunking": cls.ROW_CHUNKING,
            "markdown": cls.MARKDOWN_CHUNKING,
            "markdownchunking": cls.MARKDOWN_CHUNKING,
        }

        if strategy_name_lower in string_mapping:
            return string_mapping[strategy_name_lower]
        else:
            raise ValueError(f"Unsupported chunking strategy: {strategy_name}")

    def __str__(self) -> str:
        return self.value
