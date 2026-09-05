"""Tests for RecursiveChunking preserving document content."""

import pytest

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


@pytest.mark.parametrize("separator", ["\n", "."])
@pytest.mark.parametrize("overlap", [50, 100])
def test_short_natural_chunk_does_not_skip_content(separator, overlap):
    """A short heading must not cause the progress guard to skip the following text."""
    words = [f"word{index:03d}" for index in range(300)]
    content = f"Intro{separator}" + " ".join(words)
    strategy = RecursiveChunking(chunk_size=1000, overlap=overlap)

    chunks = strategy.chunk(Document(content=content))

    assert all(any(word in chunk.content for chunk in chunks) for word in words)
    assert all(0 < len(chunk.content) <= strategy.chunk_size for chunk in chunks)
    assert chunks[0].content.startswith("Intro")
    assert content.endswith(chunks[-1].content)
