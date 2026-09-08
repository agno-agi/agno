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


def test_short_heading_with_overlap_does_not_skip_text():
    """Regression test for issue #9969.

    When a short heading is followed by a longer body and overlap is enabled,
    the first chunk ends after the heading. The forward-progress fallback must
    not jump past body text — every word must appear in at least one chunk.
    """
    words = [f"word{i:03d}" for i in range(300)]
    content = "Intro\n" + " ".join(words)
    strategy = RecursiveChunking(chunk_size=1000, overlap=100)
    doc = Document(content=content)

    chunks = strategy.chunk(doc)

    # Every word must appear in at least one chunk — no text skipped.
    missing = [w for w in words if not any(w in c.content for c in chunks)]
    assert not missing, f"Skipped words: {missing}"


def test_multiple_short_headings_with_overlap_does_not_skip_text():
    """Multiple consecutive short headings must not cause text loss."""
    words = [f"word{i:03d}" for i in range(200)]
    content = "H1\nH2\nH3\n" + " ".join(words)
    strategy = RecursiveChunking(chunk_size=500, overlap=50)
    doc = Document(content=content)

    chunks = strategy.chunk(doc)

    missing = [w for w in words if not any(w in c.content for c in chunks)]
    assert not missing, f"Skipped words: {missing}"


def test_short_heading_with_overlap_makes_forward_progress():
    """Ensure the fix does not cause an infinite loop with short headings."""
    content = "A\n" + "b" * 50
    strategy = RecursiveChunking(chunk_size=10, overlap=5)
    doc = Document(content=content)

    chunks = strategy.chunk(doc)

    # Should terminate (no infinite loop) and cover the heading.
    assert len(chunks) > 0
    assert "A" in chunks[0].content
    # Every 'b' from the body must appear in at least one chunk.
    combined = "".join(chunk.content for chunk in chunks)
    assert combined.count("b") >= 50
