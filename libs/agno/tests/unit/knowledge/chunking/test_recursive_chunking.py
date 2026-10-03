"""Tests for RecursiveChunking at the end of a document."""

from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document


def test_long_document_still_chunks_with_overlap_and_no_duplication():
    """Test that a long document chunks with overlap and no duplicate tail."""
    strategy = RecursiveChunking(chunk_size=20, overlap=5)
    doc = Document(name="long", content="a" * 100)

    chunks = strategy.chunk(doc)

    assert [len(c.content) for c in chunks] == [20, 20, 20, 20, 20, 20, 10]


def test_last_chunk_ends_the_document_and_repeats_no_earlier_chunk():
    """Test that the final chunk reaches the end and is not a repeat."""
    content = "".join(f"{index:04d}" for index in range(75))
    strategy = RecursiveChunking(chunk_size=100, overlap=20)
    doc = Document(name="long", content=content)

    chunks = strategy.chunk(doc)

    assert content.endswith(chunks[-1].content)
    for position, chunk in enumerate(chunks):
        assert not any(chunk.content in earlier.content for earlier in chunks[:position])


def test_trailing_whitespace_does_not_become_a_chunk():
    """A slice that only holds whitespace is not a chunk of the document."""
    strategy = RecursiveChunking(chunk_size=20, overlap=0)
    doc = Document(name="doc", content=("word " * 20) + " ")

    chunks = strategy.chunk(doc)

    assert chunks
    assert all(chunk.content.strip() for chunk in chunks)
    assert "".join(chunk.content for chunk in chunks).split() == ["word"] * 20
    assert [chunk.meta_data["chunk"] for chunk in chunks] == list(range(1, len(chunks) + 1))
