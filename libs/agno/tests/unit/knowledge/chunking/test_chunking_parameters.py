"""Parameter boundaries shared by fixed and recursive chunking."""

import pytest

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.recursive import RecursiveChunking
from agno.knowledge.document.base import Document


@pytest.mark.parametrize("strategy", [FixedSizeChunking, RecursiveChunking])
@pytest.mark.parametrize("chunk_size, overlap", [(4, -2), (0, -1), (-1, -2)])
def test_invalid_parameters_are_rejected_before_chunking(strategy, chunk_size, overlap):
    with pytest.raises(ValueError):
        strategy(chunk_size=chunk_size, overlap=overlap)


@pytest.mark.parametrize("strategy", [FixedSizeChunking, RecursiveChunking])
@pytest.mark.parametrize("overlap", [0, 1, 3])
def test_valid_overlap_preserves_all_source_characters(strategy, overlap):
    content = "abcdefghijkl"
    chunks = strategy(chunk_size=4, overlap=overlap).chunk(Document(content=content))

    covered = set()
    for chunk in chunks:
        start = content.index(chunk.content)
        covered.update(range(start, start + len(chunk.content)))
    assert covered == set(range(len(content)))


@pytest.mark.parametrize("strategy", [FixedSizeChunking, RecursiveChunking])
@pytest.mark.parametrize("overlap", [4, 5])
def test_overlap_at_or_above_chunk_size_remains_invalid(strategy, overlap):
    with pytest.raises(ValueError):
        strategy(chunk_size=4, overlap=overlap)
