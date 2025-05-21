import re
from typing import List, Optional

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy


class MarkdownChunking(ChunkingStrategy):
    """
    Chunking strategy optimized for Markdown documents.
    It considers headers, paragraphs and code blocks to decide where to split the document.
    """

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._newline_size = 1

    def _create_chunk_document(
        self,
        content: str,
        document: Document,
        chunk_number: int,
        meta_data: dict,
        current_header: Optional[str] = None,
    ) -> Document:
        """Create a new Document chunk with the given content and metadata."""
        meta_data = meta_data.copy()
        meta_data["chunk"] = chunk_number
        meta_data["chunk_size"] = len(content)
        if current_header:
            meta_data["header"] = current_header

        chunk_id = None
        if document.id:
            chunk_id = f"{document.id}_{chunk_number}"
        elif document.name:
            chunk_id = f"{document.name}_{chunk_number}"

        return Document(
            id=chunk_id,
            name=document.name,
            meta_data=meta_data,
            content=content,
        )

    def _is_code_block_limit(self, line: str) -> bool:
        """Check if the line marks the start or end of a code block."""
        return line.strip().startswith("```")

    def chunk(self, document: Document) -> List[Document]:
        """Split markdown document into chunks, considering markdown structure"""
        if not document.content or len(document.content) <= self.chunk_size:
            return [document]

        chunks: List[Document] = []
        chunk_meta_data = document.meta_data or {}
        chunk_number = 1

        # Regex to match headers of level 2 or higher
        header_pattern = r"^(#{2,6})\s+(.+)$"

        # Split the content on headers
        lines = document.content.split("\n")
        current_chunk = []
        current_size = 0
        current_header = None
        in_code_block = False

        for line in lines:
            # Flag a code block is starting or ending
            if self._is_code_block_limit(line):
                in_code_block = not in_code_block

            # Process headers, if not in a code block
            if not in_code_block and re.match(header_pattern, line, re.MULTILINE):
                # If we already have content in the current chunk, save it
                if current_chunk and current_size > 0:
                    chunk_content = "\n".join(current_chunk)
                    chunks.append(
                        self._create_chunk_document(
                            chunk_content,
                            document,
                            chunk_number,
                            chunk_meta_data,
                            current_header,
                        )
                    )
                    chunk_number += 1

                # Start a new chunk with this header
                current_header = line.strip()
                current_chunk = [line]
                current_size = len(line)
            else:
                line_length = len(line)
                line_size = line_length + self._newline_size

                # If adding this line exceeds chunk size, save current chunk and start a new one
                if current_size + line_size > self.chunk_size and current_chunk:
                    # Don't split in the middle of a code block
                    if in_code_block:
                        # Continue adding to the current chunk even if it exceeds size
                        current_chunk.append(line)
                        current_size += line_size
                    else:
                        chunk_content = "\n".join(current_chunk)
                        chunks.append(
                            self._create_chunk_document(
                                chunk_content,
                                document,
                                chunk_number,
                                chunk_meta_data,
                                current_header,
                            )
                        )
                        chunk_number += 1

                        # Start a new chunk but keep the header context
                        current_chunk = []
                        if current_header:
                            current_chunk.append(current_header)
                            current_size = len(current_header)
                        else:
                            current_size = 0

                        current_chunk.append(line)
                        current_size += line_size
                else:
                    current_chunk.append(line)
                    current_size += line_size

        # Add the last chunk if it exists
        if current_chunk:
            chunk_content = "\n".join(current_chunk)
            chunks.append(
                self._create_chunk_document(
                    chunk_content,
                    document,
                    chunk_number,
                    chunk_meta_data,
                    current_header,
                )
            )

        # Handle overlap if specified
        if self.overlap > 0 and len(chunks) > 1:
            overlapped_chunks = []
            for i in range(len(chunks)):
                if i > 0:
                    # Add overlap from previous chunk
                    prev_content = chunks[i - 1].content
                    prev_text = prev_content[-min(self.overlap, len(prev_content)) :]

                    if prev_text:
                        overlapped_chunks.append(
                            self._create_chunk_document(
                                prev_text + "\n" + chunks[i].content,
                                document,
                                chunks[i].meta_data["chunk"],
                                chunks[i].meta_data,
                            )
                        )
                    else:
                        overlapped_chunks.append(chunks[i])
                else:
                    overlapped_chunks.append(chunks[i])

            return overlapped_chunks

        return chunks
