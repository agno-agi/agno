import warnings
from typing import List

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy


class RecursiveChunking(ChunkingStrategy):
    """Chunking strategy that recursively splits text into chunks by finding natural break points"""

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        # overlap must be less than chunk size
        if overlap >= chunk_size:
            raise ValueError(f"Invalid parameters: overlap ({overlap}) must be less than chunk size ({chunk_size}).")

        if overlap > chunk_size * 0.15:
            warnings.warn(
                f"High overlap: {overlap} > 15% of chunk size ({chunk_size}). May cause slow processing.",
                RuntimeWarning,
            )

        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document) -> List[Document]:
        """Recursively chunk text by finding natural break points"""
        if len(document.content) <= self.chunk_size:
            return [document]

        chunks: List[Document] = []
        start = 0
        chunk_meta_data = document.meta_data
        chunk_number = 1
        content = self.clean_text(document.content)

        while start < len(content):
            end = min(start + self.chunk_size, len(content))

            if end < len(content):
                for sep in ["\n", "."]:
                    last_sep = content[start:end].rfind(sep)
                    if last_sep != -1:
                        end = start + last_sep + 1
                        break

            chunk = content[start:end]
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = None
            if document.id:
                chunk_id = f"{document.id}_{chunk_number}"
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
