from agno.knowledge.reader.web_search_reader import WebSearchReader


def test_web_search_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    from agno.knowledge.chunking.semantic import SemanticChunking

    reader = WebSearchReader(chunk_size=900)
    assert reader.chunk_size == 900
    assert reader.chunking_strategy.chunk_size == 900
    assert isinstance(reader.chunking_strategy, SemanticChunking)


def test_web_search_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    from agno.knowledge.chunking.semantic import SemanticChunking

    reader = WebSearchReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, SemanticChunking)


def test_web_search_reader_explicit_strategy_preserved():
    """Test that explicit chunking_strategy is not overridden"""
    from agno.knowledge.chunking.fixed import FixedSizeChunking

    custom_strategy = FixedSizeChunking(chunk_size=1000)
    reader = WebSearchReader(chunk_size=500, chunking_strategy=custom_strategy)
    assert reader.chunk_size == 500
    assert reader.chunking_strategy is custom_strategy
    assert reader.chunking_strategy.chunk_size == 1000
