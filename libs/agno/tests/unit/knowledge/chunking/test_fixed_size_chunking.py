"""Tests for FixedSizeChunking with short documents and overlap."""

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.document.base import Document


def test_short_document_with_large_overlap_is_not_silently_dropped():
    """Test that a document shorter than the overlap is not dropped."""
    strategy = FixedSizeChunking(chunk_size=100, overlap=50)
    doc = Document(name="short", content="Hello world, this is short.")

    chunks = strategy.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].content == "Hello world, this is short."


def test_empty_document_still_returns_no_chunks():
    """Test that an empty document returns no chunks."""
    strategy = FixedSizeChunking(chunk_size=100, overlap=50)
    doc = Document(name="empty", content="")

    assert strategy.chunk(doc) == []


def test_long_document_still_chunks_with_overlap_and_no_duplication():
    """Test that a long document chunks with overlap and no duplicate tail."""
    strategy = FixedSizeChunking(chunk_size=20, overlap=5)
    doc = Document(name="long", content="a" * 100)

    chunks = strategy.chunk(doc)

    assert len(chunks) == 7
    assert [len(c.content) for c in chunks] == [20, 20, 20, 20, 20, 20, 10]
