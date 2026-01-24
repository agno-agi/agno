"""Tests for chunk ID generation across chunking strategies.

These tests verify the fallback chain for chunk ID generation:
1. document.id -> uses document.id
2. document.name -> uses document.name (when no id)
3. content hash -> uses MD5 hash of content (when no id or name)
"""

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.document.base import Document

# --- Tests for content hash fallback ---


def test_chunk_id_uses_document_id_when_available():
    """When document has id, chunk IDs should use it."""
    doc = Document(id="doc123", name="test.txt", content="Some content here.")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].id == "doc123_1"


def test_chunk_id_uses_document_name_when_no_id():
    """When document has name but no id, chunk IDs should use name."""
    doc = Document(name="test.txt", content="Some content here.")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].id == "test.txt_1"


def test_chunk_id_uses_content_hash_when_no_id_or_name():
    """When document has no id or name, chunk IDs should use content hash."""
    doc = Document(content="Some content here for hashing.")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].id is not None
    assert chunks[0].id.startswith("chunk_")
    # Format: chunk_{12-char-hash}_{chunk_number}
    parts = chunks[0].id.split("_")
    assert len(parts) == 3
    assert parts[0] == "chunk"
    assert len(parts[1]) == 12  # MD5 truncated to 12 chars
    assert parts[2] == "1"


def test_chunk_id_is_none_for_empty_content_without_id_or_name():
    """Empty content with no id/name returns empty list from FixedSizeChunking."""
    doc = Document(content="")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    # FixedSizeChunking returns empty list for empty content
    assert len(chunks) == 0


# --- Tests for determinism ---


def test_chunk_id_deterministic_across_runs():
    """Same content should produce same chunk IDs every time."""
    content = "Deterministic content for testing hash stability."
    doc1 = Document(content=content)
    doc2 = Document(content=content)

    chunker = FixedSizeChunking(chunk_size=100)
    chunks1 = chunker.chunk(doc1)
    chunks2 = chunker.chunk(doc2)

    assert chunks1[0].id == chunks2[0].id


def test_chunk_id_different_for_different_content():
    """Different content should produce different chunk IDs."""
    doc1 = Document(content="First document content.")
    doc2 = Document(content="Second document content.")

    chunker = FixedSizeChunking(chunk_size=100)
    chunks1 = chunker.chunk(doc1)
    chunks2 = chunker.chunk(doc2)

    assert chunks1[0].id != chunks2[0].id


def test_chunk_id_deterministic_for_multiple_chunks():
    """Multiple chunks from same document should have unique, deterministic IDs."""
    content = "A" * 100 + "B" * 100 + "C" * 100
    doc = Document(content=content)

    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    # Each chunk should have unique ID
    ids = [chunk.id for chunk in chunks]
    assert len(ids) == len(set(ids))  # All unique

    # IDs should be deterministic
    chunks2 = chunker.chunk(Document(content=content))
    ids2 = [chunk.id for chunk in chunks2]
    assert ids == ids2


# --- Tests for RowChunking ---


def test_row_chunking_uses_document_id():
    """RowChunking should use document.id when available."""
    doc = Document(id="doc123", content="row1\nrow2\nrow3")
    chunker = RowChunking()
    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert chunks[0].id == "doc123_row_1"
    assert chunks[1].id == "doc123_row_2"
    assert chunks[2].id == "doc123_row_3"


def test_row_chunking_uses_document_name_when_no_id():
    """RowChunking should use document.name when no id is present."""
    doc = Document(name="data.csv", content="row1\nrow2\nrow3")
    chunker = RowChunking()
    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    assert chunks[0].id == "data.csv_row_1"
    assert chunks[1].id == "data.csv_row_2"
    assert chunks[2].id == "data.csv_row_3"


def test_row_chunking_uses_content_hash_when_no_id_or_name():
    """RowChunking should use content hash when no id or name is present."""
    doc = Document(content="row1\nrow2\nrow3")
    chunker = RowChunking()
    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    for chunk in chunks:
        assert chunk.id is not None
        assert chunk.id.startswith("chunk_")
        assert "_row_" in chunk.id


def test_row_chunking_skip_header():
    """RowChunking with skip_header should start from row 2."""
    doc = Document(id="doc", content="header\nrow1\nrow2")
    chunker = RowChunking(skip_header=True)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 2
    assert chunks[0].id == "doc_row_2"
    assert chunks[1].id == "doc_row_3"


def test_row_chunking_empty_rows_skipped():
    """Empty rows should be skipped."""
    doc = Document(id="doc", content="row1\n\nrow2\n\n\nrow3")
    chunker = RowChunking()
    chunks = chunker.chunk(doc)

    assert len(chunks) == 3
    # Row numbers should be logical (including empty rows)
    assert chunks[0].meta_data["row_number"] == 1
    assert chunks[1].meta_data["row_number"] == 3
    assert chunks[2].meta_data["row_number"] == 6


# --- Tests for DocumentChunking ---


def test_document_chunking_produces_chunks_with_ids():
    """DocumentChunking should produce chunks with valid IDs."""
    content = "A" * 50 + "\n\n" + "B" * 50 + "\n\n" + "C" * 50
    doc = Document(content=content)

    chunker = DocumentChunking(chunk_size=60, overlap=0)
    chunks = chunker.chunk(doc)

    # All chunks should have non-None IDs
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.id is not None
        assert chunk.id.startswith("chunk_")


# --- Tests for Unicode content ---


def test_chunk_id_handles_unicode_content():
    """Unicode content should produce valid chunk IDs."""
    doc = Document(content="Hello Unicode content")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].id is not None
    assert chunks[0].id.startswith("chunk_")


def test_chunk_id_handles_emoji_content():
    """Emoji content should produce valid chunk IDs."""
    doc = Document(content="Hello emoji content")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].id is not None
    assert chunks[0].id.startswith("chunk_")


# --- Tests for chunk ID prefix ---


def test_row_chunking_id_has_row_prefix():
    """RowChunking IDs should include 'row' prefix."""
    doc = Document(id="doc", content="line1\nline2")
    chunker = RowChunking()
    chunks = chunker.chunk(doc)

    for chunk in chunks:
        assert "_row_" in chunk.id


def test_other_chunking_strategies_no_row_prefix():
    """Other chunking strategies should not include 'row' prefix."""
    doc = Document(id="doc", content="Some content")
    chunker = FixedSizeChunking(chunk_size=100)
    chunks = chunker.chunk(doc)

    for chunk in chunks:
        assert "_row_" not in chunk.id
        assert chunk.id == "doc_1"
