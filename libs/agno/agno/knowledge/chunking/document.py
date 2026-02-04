from typing import List

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


class DocumentChunking(ChunkingStrategy):
    """A chunking strategy that splits text based on document structure like paragraphs and sections"""

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document) -> List[Document]:
        """Split document into chunks based on document structure"""
        if len(document.content) <= self.chunk_size:
            return [document]

        # Split on double newlines first (paragraphs), then clean each paragraph
        raw_paragraphs = document.content.split("\n\n")
        paragraphs = [self.clean_text(para) for para in raw_paragraphs]
        chunks: List[Document] = []
        current_chunk: List[str] = []
        current_size = 0
        chunk_meta_data = document.meta_data
        chunk_number = 1

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_size = len(para)

            # If paragraph itself is larger than chunk_size, split it by sentences
            if para_size > self.chunk_size:
                # Save current chunk first
                if current_chunk:
                    meta_data = chunk_meta_data.copy()
                    meta_data["chunk"] = chunk_number
                    chunk_content = "\n\n".join(current_chunk)
                    chunk_id = self._generate_chunk_id(document, chunk_number, chunk_content)
                    meta_data["chunk_size"] = len(chunk_content)
                    chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))
                    chunk_number += 1
                    current_chunk = []
                    current_size = 0

                # Split oversized paragraph by sentences
                import re

                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    sentence_size = len(sentence)

                    if current_size + sentence_size <= self.chunk_size:
                        current_chunk.append(sentence)
                        current_size += sentence_size
                    else:
                        if current_chunk:
                            meta_data = chunk_meta_data.copy()
                            meta_data["chunk"] = chunk_number
                            chunk_content = " ".join(current_chunk)
                            chunk_id = self._generate_chunk_id(document, chunk_number, chunk_content)
                            meta_data["chunk_size"] = len(chunk_content)
                            chunks.append(
                                Document(
                                    id=chunk_id,
                                    name=document.name,
                                    meta_data=meta_data,
                                    content=chunk_content,
                                )
                            )
                            chunk_number += 1
                        current_chunk = [sentence]
                        current_size = sentence_size

            elif current_size + para_size <= self.chunk_size:
                current_chunk.append(para)
                current_size += para_size
            else:
                meta_data = chunk_meta_data.copy()
                meta_data["chunk"] = chunk_number
                chunk_content = "\n\n".join(current_chunk)
                chunk_id = self._generate_chunk_id(document, chunk_number, chunk_content)
                meta_data["chunk_size"] = len(chunk_content)
                if current_chunk:
                    chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))
                    chunk_number += 1
                current_chunk = [para]
                current_size = para_size

        if current_chunk:
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_content = "\n\n".join(current_chunk)
            chunk_id = self._generate_chunk_id(document, chunk_number, chunk_content)
            meta_data["chunk_size"] = len(chunk_content)
            chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))

        # Handle overlap if specified
        if self.overlap > 0:
            overlapped_chunks = []
            for i in range(len(chunks)):
                if i > 0:
                    # Add overlap from previous chunk
                    prev_text = chunks[i - 1].content[-self.overlap :]
                    meta_data = chunk_meta_data.copy()
                    # Use the chunk's existing metadata and ID instead of stale chunk_number
                    meta_data["chunk"] = chunks[i].meta_data["chunk"]
                    chunk_id = chunks[i].id
                    meta_data["chunk_size"] = len(prev_text + chunks[i].content)

                    if prev_text:
                        overlapped_chunks.append(
                            Document(
                                id=chunk_id,
                                name=document.name,
                                meta_data=meta_data,
                                content=prev_text + chunks[i].content,
                            )
                        )
                    else:
                        overlapped_chunks.append(chunks[i])
                else:
                    overlapped_chunks.append(chunks[i])
            chunks = overlapped_chunks

        return chunks
