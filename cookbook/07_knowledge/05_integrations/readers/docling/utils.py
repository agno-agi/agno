"""
Docling Reader: Shared Utilities
=================================
Common setup and utilities for Docling reader examples.

Docling uses IBM's advanced document conversion library to extract content from multiple document formats.

Supported formats examples::
- PDF: PDFs with advanced layout understanding and text extraction
- DOCX: Microsoft Word documents with structure preservation
- PPTX: PowerPoint presentations
- Markdown: Markdown files
- CSV: CSV spreadsheets
- XLSX: Excel spreadsheets

Output formats examples:
- markdown: Preserves structure and formatting
- text: Plain text output
- json: Lossless serialization with full document structure
- html: HTML with image embedding/referencing support
- doctags: Markup format with full content and layout characteristics

Key features:
- Advanced document structure understanding
- Better handling of complex layouts (tables, columns, etc.)
- Multiple output formats for different use cases
- Ideal for complex documents with rich formatting

Run `uv pip install docling openai-whisper` to install python dependencies.
System requirement ffmpeg (https://www.ffmpeg.org/download.html) for audio formats.

See also: 01_documents.py for PDF/DOCX, 02_data.py for CSV/JSON and 03_web.py for web sources.
"""

import warnings

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.lancedb import LanceDb, SearchType

# Suppress Whisper FP16 warnings when running on CPU
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")


def get_knowledge(table_name: str = "docling_reader") -> Knowledge:
    return Knowledge(
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name=table_name,
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )


def get_agent(knowledge: Knowledge) -> Agent:
    return Agent(
        model=OpenAIResponses(id="gpt-5.2"),
        knowledge=knowledge,
        search_knowledge=True,
        markdown=True,
    )
