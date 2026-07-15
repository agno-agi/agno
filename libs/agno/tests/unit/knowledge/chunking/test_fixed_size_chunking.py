"""Regression tests for FixedSizeChunking.

The loop guard `while start + self.overlap < content_length` (rather than
just `while start < content_length`) meant a document shorter than
`self.overlap` characters never entered the loop body at all -- the entire
document was silently dropped with zero chunks returned, no error or
warning. `overlap` is only validated to be `< chunk_size` in the
constructor, not `< len(content)`, so this was easy to hit with a large
chunk_size/overlap pair applied to a short document.
"""

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.document.base import Document


def test_short_document_with_large_overlap_is_not_silently_dropped():
    strategy = FixedSizeChunking(chunk_size=100, overlap=50)
    doc = Document(name="short", content="Hello world, this is short.")

    chunks = strategy.chunk(doc)

    assert len(chunks) == 1
    assert chunks[0].content == "Hello world, this is short."


def test_empty_document_still_returns_no_chunks():
    strategy = FixedSizeChunking(chunk_size=100, overlap=50)
    doc = Document(name="empty", content="")

    assert strategy.chunk(doc) == []


def test_long_document_still_chunks_with_overlap_and_no_duplication():
    """A naive fix that only widens the loop guard (without also stopping
    once a chunk reaches the end of the content) causes `new_start` to
    barely advance when overlap is large relative to the remaining
    content, re-emitting near-duplicate chunks one character apart instead
    of terminating cleanly at the end of the document."""
    strategy = FixedSizeChunking(chunk_size=20, overlap=5)
    doc = Document(name="long", content="a" * 100)

    chunks = strategy.chunk(doc)

    assert len(chunks) == 7
    assert [len(c.content) for c in chunks] == [20, 20, 20, 20, 20, 20, 10]
