import os
import tempfile
from typing import List

try:
    from unstructured.chunking.title import chunk_by_title  # type: ignore
    from unstructured.partition.md import partition_md  # type: ignore
except ImportError:
    raise ImportError("`unstructured` not installed. Please install it using `pip install unstructured markdown`")

from agno.document.base import Document
from agno.document.chunking.strategy import ChunkingStrategy


class MarkdownChunking(ChunkingStrategy):
    """A chunking strategy that splits markdown based on structure like headers, paragraphs and sections"""

    def __init__(self, chunk_size: int = 5000, overlap: int = 0):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def _partition_markdown_content(self, content: str) -> List[str]:
        """
        Partition markdown content and return a list of text chunks.
        Falls back to paragraph splitting if the markdown chunking fails.
        """
        try:
            # Create a temporary file with the markdown content.
            # This is the recommended usage of the unstructured library.
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name

            try:
                elements = partition_md(filename=temp_file_path)

                if not elements:
                    return self.clean_text(content).split("\n\n")

                # Chunk by title with some default values
                chunked_elements = chunk_by_title(
                    elements=elements,
                    max_characters=self.chunk_size,
                    new_after_n_chars=int(self.chunk_size * 0.8),
                    combine_text_under_n_chars=500,
                    overlap=0,
                )

                # Generate the final text chunks
                text_chunks = []
                for chunk_group in chunked_elements:
                    if isinstance(chunk_group, list):
                        chunk_text = "\n\n".join([elem.text for elem in chunk_group if hasattr(elem, "text")])
                    else:
                        chunk_text = chunk_group.text if hasattr(chunk_group, "text") else str(chunk_group)

                    if chunk_text.strip():
                        text_chunks.append(chunk_text.strip())

                return text_chunks if text_chunks else self.clean_text(content).split("\n\n")

            # Always clean up the temporary file
            finally:
                os.unlink(temp_file_path)

        # Fallback to simple paragraph splitting if the markdown chunking fails
        except Exception:
            return self.clean_text(content).split("\n\n")

    def chunk(self, document: Document) -> List[Document]:
        """Split markdown document into chunks based on markdown structure"""
        if not document.content or len(document.content) <= self.chunk_size:
            return [document]

        # Split using markdown chunking logic, or fallback to paragraphs
        sections = self._partition_markdown_content(document.content)

        chunks: List[Document] = []
        current_chunk = []
        current_size = 0
        chunk_meta_data = document.meta_data
        chunk_number = 1

        for section in sections:
            section = section.strip()
            section_size = len(section)

            if current_size + section_size <= self.chunk_size:
                current_chunk.append(section)
                current_size += section_size
            else:
                meta_data = chunk_meta_data.copy()
                meta_data["chunk"] = chunk_number
                chunk_id = None
                if document.id:
                    chunk_id = f"{document.id}_{chunk_number}"
                elif document.name:
                    chunk_id = f"{document.name}_{chunk_number}"
                meta_data["chunk_size"] = len("\n\n".join(current_chunk))

                if current_chunk:
                    chunks.append(
                        Document(
                            id=chunk_id, name=document.name, meta_data=meta_data, content="\n\n".join(current_chunk)
                        )
                    )
                    chunk_number += 1

                current_chunk = [section]
                current_size = section_size

        if current_chunk:
            meta_data = chunk_meta_data.copy()
            meta_data["chunk"] = chunk_number
            chunk_id = None
            if document.id:
                chunk_id = f"{document.id}_{chunk_number}"
            elif document.name:
                chunk_id = f"{document.name}_{chunk_number}"
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
                    meta_data = chunk_meta_data.copy()
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
