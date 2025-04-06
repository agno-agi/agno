from typing import List, Optional

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy
from agno.models.base import Model
from agno.models.message import Message


class RowChunking(ChunkingStrategy):
    """Chunking strategy that treats each row in a CSV file as a separate chunk."""

    def __init__(self):
        pass

    def chunk(self, document: Document) -> List[Document]:
        """Split the document into chunks, each representing a row in the CSV."""
        rows = document.content.splitlines()
        chunks = []
        for i, row in enumerate(rows):
            chunk_content = row.strip()
            if chunk_content:
                meta_data = document.meta_data.copy()
                meta_data["row_number"] = i + 1  # 1-based index
                chunk_id = f"{document.id}_row_{i + 1}" if document.id else None
                chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))
        return chunks
