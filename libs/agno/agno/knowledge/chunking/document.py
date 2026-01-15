import hashlib
from typing import List, Optional

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


class DocumentChunking(ChunkingStrategy):
    """A chunking strategy that splits text based on document structure like paragraphs and sections"""

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0:
            raise ValueError("overlap cannot be negative")
        if overlap >= chunk_size:
            raise ValueError("overlap must be less than chunk_size")
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
            # Use the original document content for consistency across chunks
            hash_source = content if content else document.content
            content_hash = hashlib.md5(hash_source.encode()).hexdigest()[:12]
            return f"chunk_{content_hash}_{chunk_number}"

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
                    chunk_id = self._generate_chunk_id(document, chunk_number)
                    meta_data["chunk_size"] = len("\n\n".join(current_chunk))
                    chunks.append(
                        Document(
                            id=chunk_id, name=document.name, meta_data=meta_data, content="\n\n".join(current_chunk)
                        )
                    )
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
                            chunk_id = self._generate_chunk_id(document, chunk_number)
                            meta_data["chunk_size"] = len(" ".join(current_chunk))
                            chunks.append(
                                Document(
                                    id=chunk_id,
                                    name=document.name,
                                    meta_data=meta_data,
                                    content=" ".join(current_chunk),
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
                chunk_id = self._generate_chunk_id(document, chunk_number)
                meta_data["chunk_size"] = len("\n\n".join(current_chunk))
                if current_chunk:
                    chunks.append(
                        Document(
                            id=chunk_id, name=document.name, meta_data=meta_data, content="\n\n".join(current_chunk)
                        )
                    )
                    chunk_number += 1
                current_chunk = [para]
                current_size = para_size

        if current_chunk:
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = self._generate_chunk_id(document, chunk_number)
            meta_data["chunk_size"] = len("\n\n".join(current_chunk))
            chunks.append(
                Document(id=chunk_id, name=document.name, meta_data=meta_data, content="\n\n".join(current_chunk))
            )

        # Handle overlap if specified
        if self.overlap > 0:
            overlapped_chunks = []
            for i in range(len(chunks)):
                if i > 0:
                    # Add overlap from previous chunk
                    prev_text = chunks[i - 1].content[-self.overlap :]
                    if prev_text:
                        # Create new chunk with overlap prepended
                        overlapped_chunks.append(
                            Document(
                                id="",  # Will be renumbered below
                                name=document.name,
                                meta_data=chunk_meta_data.copy(),
                                content=prev_text + chunks[i].content,
                            )
                        )
                else:
                    overlapped_chunks.append(chunks[i])
            chunks = overlapped_chunks

            # Renumber all chunks sequentially after overlap processing
            for idx, chunk in enumerate(chunks, start=1):
                chunk.id = self._generate_chunk_id(document, idx)
                chunk.meta_data["chunk"] = idx
                chunk.meta_data["chunk_size"] = len(chunk.content)

        return chunks
