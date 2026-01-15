import hashlib
import warnings
from typing import List, Optional

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


class RecursiveChunking(ChunkingStrategy):
    """Chunking strategy that recursively splits text into chunks by finding natural break points"""

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        # Bug fix: validate chunk_size is positive to prevent issues
        if chunk_size <= 0:
            raise ValueError(f"Invalid parameters: chunk_size ({chunk_size}) must be greater than 0.")
        # overlap must be less than chunk size
        if overlap >= chunk_size:
            raise ValueError(f"Invalid parameters: overlap ({overlap}) must be less than chunk size ({chunk_size}).")
        if overlap < 0:
            raise ValueError(f"Invalid parameters: overlap ({overlap}) must be non-negative.")

        if overlap > chunk_size * 0.15:
            warnings.warn(
                f"High overlap: {overlap} > 15% of chunk size ({chunk_size}). May cause slow processing.",
                RuntimeWarning,
            )

        self.chunk_size = chunk_size
        self.overlap = overlap

    def _generate_chunk_id(self, document: Document, chunk_number: int, content: Optional[str] = None) -> str:
        """Generate a unique chunk ID.

        Uses document.id or document.name if available, otherwise falls back
        to a content hash to ensure unique IDs even for documents without
        explicit identifiers.
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

    def chunk(self, document: Document) -> List[Document]:
        """Recursively chunk text by finding natural break points"""
        if len(document.content) <= self.chunk_size:
            return [document]

        chunks: List[Document] = []
        start = 0
        chunk_meta_data = document.meta_data
        chunk_number = 1
        content = document.content

        while start < len(content):
            end = min(start + self.chunk_size, len(content))

            if end < len(content):
                for sep in ["\n", "."]:
                    last_sep = content[start:end].rfind(sep)
                    if last_sep != -1:
                        end = start + last_sep + 1
                        break

            chunk = self.clean_text(content[start:end])
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = self._generate_chunk_id(document, chunk_number, chunk)
            chunk_number += 1
            meta_data["chunk_size"] = len(chunk)
            chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk))

            new_start = end - self.overlap
            if new_start <= start:  # Prevent infinite loop
                new_start = min(
                    len(content), start + max(1, self.chunk_size // 10)
                )  # Move forward by at least 10% of chunk size
            start = new_start

        return chunks
