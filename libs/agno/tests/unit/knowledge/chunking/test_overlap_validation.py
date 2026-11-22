"""Chunking strategies agree on which overlap values are invalid."""

import pytest

from agno.knowledge.chunking.document import DocumentChunking
from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document

STRATEGIES = [DocumentChunking, FixedSizeChunking, RecursiveChunking]


@pytest.mark.parametrize("strategy", STRATEGIES)
@pytest.mark.parametrize("overlap", [100, 150])
def test_overlap_not_smaller_than_chunk_size_is_rejected(strategy, overlap):
    """An overlap of chunk_size or more is rejected instead of overshooting it."""
    with pytest.raises(ValueError, match="must be less than chunk size"):
        strategy(chunk_size=100, overlap=overlap)


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_largest_valid_overlap_still_chunks(strategy):
    """The largest valid overlap is accepted and returns chunks."""
    chunker = strategy(chunk_size=100, overlap=99)

    chunks = chunker.chunk(Document(name="doc", content="word " * 100))

    assert chunks
    assert all(chunk.content for chunk in chunks)
