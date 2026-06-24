from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.row import RowChunking
from agno.knowledge.document.base import Document

# --- Fallback chain tests ---


def test_fallback_priority_1_uses_document_id():
    """When document has id, chunk ID uses document.id regardless of name."""
    doc = Document(id="doc123", name="test.txt", content="Some content.")
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    assert chunks[0].id == "doc123_1"


def test_fallback_priority_2_uses_document_name():
    """When document has name but no id, chunk ID uses document.name."""
    doc = Document(name="report.pdf", content="Some content.")
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    assert chunks[0].id == "report.pdf_1"


def test_fallback_priority_3_uses_content_hash():
    """When document has neither id nor name, chunk ID uses content hash."""
    doc = Document(content="Content for hashing.")
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    assert chunks[0].id is not None
    assert chunks[0].id.startswith("chunk_")
    # Format: chunk_{12-char-hash}_{chunk_number}
    parts = chunks[0].id.split("_")
    assert len(parts) == 3
    assert parts[0] == "chunk"
    assert len(parts[1]) == 12
    assert parts[2] == "1"


# --- Determinism tests ---


def test_same_content_produces_same_hash():
    """Identical content should produce identical chunk IDs."""
    content = "Deterministic content."
    chunks1 = FixedSizeChunking(chunk_size=100).chunk(Document(content=content))
    chunks2 = FixedSizeChunking(chunk_size=100).chunk(Document(content=content))

    assert chunks1[0].id == chunks2[0].id


def test_different_content_produces_different_hash():
    """Different content should produce different chunk IDs."""
    chunks1 = FixedSizeChunking(chunk_size=100).chunk(Document(content="Content A"))
    chunks2 = FixedSizeChunking(chunk_size=100).chunk(Document(content="Content B"))

    assert chunks1[0].id != chunks2[0].id


def test_multiple_chunks_have_unique_ids():
    """Each chunk from the same document should have a unique ID."""
    doc = Document(content="A" * 100 + "B" * 100 + "C" * 100)
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    ids = [c.id for c in chunks]
    assert len(ids) == len(set(ids)), "Chunk IDs should be unique"


# --- RowChunking prefix tests ---


def test_row_chunking_id_format_with_document_id():
    """RowChunking should produce IDs with _row_ prefix."""
    doc = Document(id="data", content="row1\nrow2\nrow3")
    chunks = RowChunking().chunk(doc)

    assert chunks[0].id == "data_row_1"
    assert chunks[1].id == "data_row_2"
    assert chunks[2].id == "data_row_3"


def test_row_chunking_id_format_with_name():
    """RowChunking should use name with _row_ prefix when no id."""
    doc = Document(name="data.csv", content="row1\nrow2")
    chunks = RowChunking().chunk(doc)

    assert chunks[0].id == "data.csv_row_1"
    assert chunks[1].id == "data.csv_row_2"


def test_row_chunking_id_format_with_hash():
    """RowChunking should use hash with _row_ prefix when no id/name."""
    doc = Document(content="row1\nrow2")
    chunks = RowChunking().chunk(doc)

    assert chunks[0].id.startswith("chunk_")
    assert "_row_" in chunks[0].id
    assert chunks[0].id.endswith("_row_1")


# --- Edge cases ---


def test_empty_content_returns_no_chunks():
    """Empty content should return empty list (no ID generation needed)."""
    doc = Document(content="")
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    assert len(chunks) == 0


def test_unicode_content_produces_valid_id():
    """Unicode content should hash correctly."""
    doc = Document(content="Hello")
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    assert chunks[0].id is not None
    assert chunks[0].id.startswith("chunk_")


def test_emoji_content_produces_valid_id():
    """Emoji content should hash correctly."""
    doc = Document(content="Hello world")
    chunks = FixedSizeChunking(chunk_size=100).chunk(doc)

    assert chunks[0].id is not None
    assert chunks[0].id.startswith("chunk_")


def test_document_chunking_uses_fallback():
    """DocumentChunking should also use the fallback chain."""
    doc = Document(content="Para one.\n\nPara two.\n\nPara three.")
    chunks = DocumentChunking(chunk_size=20, overlap=0).chunk(doc)

    assert len(chunks) >= 2
    for chunk in chunks:
        assert chunk.id is not None
        assert chunk.id.startswith("chunk_")
