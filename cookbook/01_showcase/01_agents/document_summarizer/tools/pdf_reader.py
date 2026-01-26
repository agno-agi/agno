"""
PDF Reader Tool
===============

Extracts text content from PDF files.
"""

from pathlib import Path
from typing import Optional

from agno.utils.log import logger

try:
    from pypdf import PdfReader
except ImportError:
    raise ImportError("`pypdf` not installed. Please install using `pip install pypdf`")


# ============================================================================
# PDF Reader Tool
# ============================================================================
def read_pdf(file_path: str, max_pages: Optional[int] = None) -> str:
    """Read and extract text from a PDF file.

    Args:
        file_path: Path to the PDF file.
        max_pages: Maximum number of pages to read. None for all pages.

    Returns:
        Extracted text content from the PDF.
    """
    path = Path(file_path)
    if not path.exists():
        return f"Error: File not found: {file_path}"

    if not path.suffix.lower() == ".pdf":
        return f"Error: Not a PDF file: {file_path}"

    try:
        reader = PdfReader(str(path))
        total_pages = len(reader.pages)
        pages_to_read = min(total_pages, max_pages) if max_pages else total_pages

        logger.info(f"Reading PDF: {path.name} ({pages_to_read}/{total_pages} pages)")

        text_parts = []
        for i in range(pages_to_read):
            page = reader.pages[i]
            text = page.extract_text()
            if text:
                text_parts.append(f"--- Page {i + 1} ---\n{text}")

        if not text_parts:
            return "Warning: No text content found in PDF. The document may contain only images."

        content = "\n\n".join(text_parts)

        # Add metadata
        metadata_parts = [f"File: {path.name}", f"Pages: {pages_to_read}/{total_pages}"]

        if reader.metadata:
            if reader.metadata.title:
                metadata_parts.append(f"Title: {reader.metadata.title}")
            if reader.metadata.author:
                metadata_parts.append(f"Author: {reader.metadata.author}")

        metadata = "\n".join(metadata_parts)
        return f"{metadata}\n\n{content}"

    except Exception as e:
        logger.error(f"Error reading PDF {file_path}: {e}")
        return f"Error reading PDF: {e}"
