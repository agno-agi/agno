from typing import List

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


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
                row_number = start_index + i
                meta_data["row_number"] = row_number  # Preserve logical row numbering
                chunk_id = self._generate_chunk_id(document, row_number, chunk_content, prefix="row")
                chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))
        return chunks
