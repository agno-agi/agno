"""
Tests for text splitting behavior in chunking strategies.
"""

from unittest.mock import patch

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document

pytest.importorskip("unstructured")
from agno.knowledge.chunking.markdown import MarkdownChunking


class TestDocumentChunkingParagraphSplit:
    """DocumentChunking should split text at paragraph boundaries"""

    def test_splits_at_paragraph_boundaries(self):
        """Text with paragraph breaks should produce multiple chunks."""
        text = """First paragraph here.

Second paragraph here.

Third paragraph here."""

        doc = Document(id="test", name="test", content=text)
        chunker = DocumentChunking(chunk_size=30, overlap=0)
        chunks = chunker.chunk(doc)

        assert len(chunks) > 1


class TestRecursiveChunkingNewlineSplit:
    """RecursiveChunking should split text at newline boundaries."""

    def test_splits_at_newline_boundary(self):
        """Text should split exactly at newline positions."""
        text = "AAAAAAAAAA\nBBBBBBBBBB"

        doc = Document(id="test", name="test", content=text)
        chunker = RecursiveChunking(chunk_size=15, overlap=0)
        chunks = chunker.chunk(doc)

        assert len(chunks) == 2
        assert chunks[0].content.strip() == "AAAAAAAAAA"
        assert chunks[1].content.strip() == "BBBBBBBBBB"


class TestMarkdownChunkingFallbackSplit:
    """MarkdownChunking fallback should split at paragraph boundaries."""

    def test_fallback_splits_at_paragraphs(self):
        """When markdown parsing fails, should fall back to paragraph splitting."""
        text = """First paragraph.

Second paragraph.

Third paragraph."""

        doc = Document(id="test", name="test", content=text)
        chunker = MarkdownChunking(chunk_size=30, overlap=0)

        with patch("agno.knowledge.chunking.markdown.partition_md", side_effect=Exception("test")):
            chunks = chunker.chunk(doc)

        assert len(chunks) > 1
