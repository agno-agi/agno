from agno.knowledge.reader.markdown_reader import MarkdownReader


def test_markdown_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    reader = MarkdownReader(chunk_size=200)
    assert reader.chunk_size == 200
    assert reader.chunking_strategy.chunk_size == 200


def test_markdown_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    reader = MarkdownReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
