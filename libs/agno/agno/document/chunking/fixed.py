from typing import List

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy


class FixedSizeChunking(ChunkingStrategy):
    """Chunking strategy that splits text into fixed-size chunks with optional overlap"""

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        # overlap must be less than chunk size
        if overlap >= chunk_size:
            raise ValueError(f"Invalid parameters: overlap ({overlap}) must be less than chunk size ({chunk_size}).")

        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document) -> List[Document]:
        """Split document into fixed-size chunks with optional overlap"""
        content = self.clean_text(document.content)
        content_length = len(content)
        chunked_documents: List[Document] = []
        chunk_number = 1
        chunk_meta_data = document.meta_data

        start = 0
        while start + self.overlap < content_length:
            end = min(start + self.chunk_size, content_length)

            # Ensure we're not splitting a word in half
            if end < content_length:
                while end > start and content[end] not in [" ", "\n", "\r", "\t"]:
                    end -= 1

            # If the entire chunk is a word, then just split it at chunk_size
            if end == start:
                end = start + self.chunk_size

            chunk = content[start:end]
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = None
            if document.id:
                chunk_id = f"{document.id}_{chunk_number}"
            elif document.name:
                chunk_id = f"{document.name}_{chunk_number}"
            meta_data["chunk_size"] = len(chunk)
            chunked_documents.append(
                Document(
                    id=chunk_id,
                    name=document.name,
                    meta_data=meta_data,
                    content=chunk,
                )
            )
            chunk_number += 1
            start = end - self.overlap

        return chunked_documents
