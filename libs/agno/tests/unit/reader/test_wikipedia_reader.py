import pytest

pytest.importorskip("wikipedia")

from agno.knowledge.reader.wikipedia_reader import WikipediaReader


def test_wikipedia_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    from agno.knowledge.chunking.fixed import FixedSizeChunking

    reader = WikipediaReader(chunk_size=550)
    assert reader.chunk_size == 550
    assert reader.chunking_strategy.chunk_size == 550
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)


def test_wikipedia_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    from agno.knowledge.chunking.fixed import FixedSizeChunking

    reader = WikipediaReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)
