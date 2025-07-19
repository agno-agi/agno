from typing import List

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy


class RowChunking(ChunkingStrategy):
    def __init__(self, skip_header: bool = False, clean_rows: bool = True):
        self.skip_header = skip_header
        self.clean_rows = clean_rows

    def chunk(self, document: Document) -> List[Document]:
        if not document or not document.content:
            return []

        if not isinstance(document.content, str):
            raise ValueError("Document content must be a string")

        rows = document.content.splitlines()

        if self.skip_header and rows:
            rows = rows[1:]
            start_index = 2
        else:
            start_index = 1

        chunks = []
        for i, row in enumerate(rows):
            if self.clean_rows:
                chunk_content = " ".join(row.split())  # Normalize internal whitespace
            else:
                chunk_content = row.strip()

            if chunk_content:  # Skip empty rows
                meta_data = document.meta_data.copy()
                meta_data["row_number"] = start_index + i  # Preserve logical row numbering
                chunk_id = f"{document.id}_row_{start_index + i}" if document.id else None
                chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))
        return chunks
