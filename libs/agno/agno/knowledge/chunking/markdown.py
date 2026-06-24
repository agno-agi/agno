import os
import re
import tempfile
from typing import List, Union

try:
    from unstructured.chunking.title import chunk_by_title  # type: ignore
    from unstructured.partition.md import partition_md  # type: ignore
except ImportError:
    raise ImportError("`unstructured` not installed. Please install it using `pip install unstructured markdown`")

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document


class MarkdownChunking(ChunkingStrategy):
    """A chunking strategy that splits markdown based on structure like headers, paragraphs and sections

    Args:
        chunk_size: Maximum size of each chunk in characters
        overlap: Number of characters to overlap between chunks
        split_on_headings: Controls heading-based splitting behavior:
            - False: Use size-based chunking (default)
            - True: Split on all headings (H1-H6)
            - int: Split on headings at or above this level (1-6)
                  e.g., 2 splits on H1 and H2, keeping H3-H6 content together
    """

    def __init__(self, chunk_size: int = 5000, overlap: int = 0, split_on_headings: Union[bool, int] = False):
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.split_on_headings = split_on_headings

        # Validate split_on_headings parameter
        # Note: In Python, isinstance(False, int) is True, so we exclude booleans explicitly
        if isinstance(split_on_headings, int) and not isinstance(split_on_headings, bool):
            if not (1 <= split_on_headings <= 6):
                raise ValueError("split_on_headings must be between 1 and 6 when using integer value")

    def _split_large_section(self, section: str) -> List[str]:
        """
        Split a large section into smaller chunks while preserving the heading context.
        Each sub-chunk will include the original heading for context.

        Args:
            section: The section content to split (may start with a heading)

        Returns:
            List of chunks, each respecting chunk_size
        """
        if len(section) <= self.chunk_size:
            return [section]

        # Extract heading and content from the section
        lines = section.split("\n")
        if lines and re.match(r"^#{1,6}\s+", lines[0]):
            heading = lines[0]
            content_lines = lines[1:]
        else:
            heading = ""
            content_lines = lines

        content = "\n".join(content_lines).strip()

        # If just heading and small content, return as-is
        if not content or len(section) <= self.chunk_size:
            return [section]

        # Split content by paragraphs
        paragraphs = re.split(r"\n\n+", content)

        chunks: List[str] = []
        current_chunk_content: List[str] = []
        # Account for heading size in each chunk
        heading_size = len(heading) + 2 if heading else 0  # +2 for "\n\n"

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            current_size = sum(len(p) for p in current_chunk_content) + len(current_chunk_content) * 2  # \n\n
            para_size = len(para)

            # Check if adding this paragraph would exceed chunk_size
            if current_chunk_content and (heading_size + current_size + para_size + 2) > self.chunk_size:
                # Save current chunk
                chunk_text = (
                    heading + "\n\n" + "\n\n".join(current_chunk_content)
                    if heading
                    else "\n\n".join(current_chunk_content)
                )
                chunks.append(chunk_text.strip())
                current_chunk_content = []

            # If single paragraph exceeds chunk_size, split it further
            if para_size + heading_size > self.chunk_size:
                # Save any accumulated content first
                if current_chunk_content:
                    chunk_text = (
                        heading + "\n\n" + "\n\n".join(current_chunk_content)
                        if heading
                        else "\n\n".join(current_chunk_content)
                    )
                    chunks.append(chunk_text.strip())
                    current_chunk_content = []

                # Split the large paragraph by sentences or fixed size
                available_size = self.chunk_size - heading_size
                words = para.split()
                current_words: List[str] = []
                current_word_len = 0

                for word in words:
                    if current_word_len + len(word) + 1 > available_size and current_words:
                        chunk_text = heading + "\n\n" + " ".join(current_words) if heading else " ".join(current_words)
                        chunks.append(chunk_text.strip())
                        current_words = []
                        current_word_len = 0
                    current_words.append(word)
                    current_word_len += len(word) + 1

                if current_words:
                    current_chunk_content.append(" ".join(current_words))
            else:
                current_chunk_content.append(para)

        # add the remaining content
        if current_chunk_content:
            chunk_text = (
                heading + "\n\n" + "\n\n".join(current_chunk_content) if heading else "\n\n".join(current_chunk_content)
            )
            chunks.append(chunk_text.strip())

        return chunks if chunks else [section]

    def _split_by_headings(self, content: str) -> List[str]:
        """
        Split markdown content by headings, keeping each heading with its content.
        Returns a list of sections where each section starts with a heading.

        When split_on_headings is an int, only splits on headings at or above that level.
        For example, split_on_headings=2 splits on H1 and H2, keeping H3-H6 content together.
        """
        # Determine which heading levels to split on
        if isinstance(self.split_on_headings, int) and not isinstance(self.split_on_headings, bool):
            # Split on headings at or above this level (1 to split_on_headings)
            max_heading_level = self.split_on_headings
            heading_pattern = rf"^#{{{1},{max_heading_level}}}\s+.+$"
        else:
            # split_on_headings is True: split on all headings (# to ######)
            heading_pattern = r"^#{1,6}\s+.+$"

        # Split content while keeping the delimiter (heading)
        # Use non-capturing group for the pattern to avoid extra capture groups
        parts = re.split(f"({heading_pattern})", content, flags=re.MULTILINE)

        sections = []
        current_section = ""

        for part in parts:
            if not part or not part.strip():
                continue

            # Check if this part is a heading
            if re.match(heading_pattern, part.strip(), re.MULTILINE):
                # Save previous section if exists
                if current_section.strip():
                    sections.append(current_section.strip())
                # Start new section with this heading
                current_section = part
            else:
                # Add content to current section
                current_section += "\n\n" + part if current_section else part

        # Don't forget the last section
        if current_section.strip():
            sections.append(current_section.strip())

        return sections if sections else [content]

    def _partition_markdown_content(self, content: str) -> List[str]:
        """
        Partition markdown content and return a list of text chunks.
        Falls back to paragraph splitting if the markdown chunking fails.
        """
        # When split_on_headings is True or an int, use regex-based splitting to preserve headings
        if self.split_on_headings:
            return self._split_by_headings(content)

        try:
            # Create a temporary file with the markdown content.
            # This is the recommended usage of the unstructured library.
            with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as temp_file:
                temp_file.write(content)
                temp_file_path = temp_file.name

            try:
                elements = partition_md(filename=temp_file_path)

                if not elements:
                    raw_paragraphs = content.split("\n\n")
                    return [self.clean_text(para) for para in raw_paragraphs]

                chunked_elements = chunk_by_title(
                    elements=elements,
                    max_characters=self.chunk_size,
                    new_after_n_chars=int(self.chunk_size * 0.8),
                    combine_text_under_n_chars=self.chunk_size,
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

                if text_chunks:
                    return text_chunks
                raw_paragraphs = content.split("\n\n")
                return [self.clean_text(para) for para in raw_paragraphs]

            # Always clean up the temporary file
            finally:
                os.unlink(temp_file_path)

        # Fallback to simple paragraph splitting if the markdown chunking fails
        except Exception:
            raw_paragraphs = content.split("\n\n")
            return [self.clean_text(para) for para in raw_paragraphs]

    def chunk(self, document: Document) -> List[Document]:
        """Split markdown document into chunks based on markdown structure"""
        # If content is empty, return as-is
        if not document.content:
            return [document]

        # When split_on_headings is enabled, always split by headings regardless of size
        # Only skip chunking for small content when using size-based chunking
        if not self.split_on_headings and len(document.content) <= self.chunk_size:
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

            # When split_on_headings is True or an int, each section becomes its own chunk
            # But if section exceeds chunk_size, split it further
            if self.split_on_headings:
                # Split large sections to respect chunk_size
                sub_chunks = self._split_large_section(section)
                for sub_chunk in sub_chunks:
                    meta_data = chunk_meta_data.copy()
                    meta_data["chunk"] = chunk_number
                    chunk_id = self._generate_chunk_id(document, chunk_number, sub_chunk)
                    meta_data["chunk_size"] = len(sub_chunk)

                    chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=sub_chunk))
                    chunk_number += 1
            elif current_size + section_size <= self.chunk_size:
                current_chunk.append(section)
                current_size += section_size
            else:
                meta_data = chunk_meta_data.copy()
                meta_data["chunk"] = chunk_number
                chunk_content = "\n\n".join(current_chunk)
                chunk_id = self._generate_chunk_id(document, chunk_number, chunk_content)
                meta_data["chunk_size"] = len(chunk_content)

                if current_chunk:
                    chunks.append(Document(id=chunk_id, name=document.name, meta_data=meta_data, content=chunk_content))
                    chunk_number += 1

                current_chunk = [section]
                current_size = section_size

        # Handle remaining content (only when not split_on_headings)
        if current_chunk and not self.split_on_headings:
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
