from agno.knowledge.reader.reader_factory import ReaderFactory
from agno.knowledge.reader.text_reader import TextReader


def test_create_reader_with_custom_chunk_size():
    """Verify create_reader('text', chunk_size=500) returns a TextReader with chunk_size == 500."""
    reader = ReaderFactory.create_reader("text", chunk_size=500)
    assert isinstance(reader, TextReader)
    assert reader.chunk_size == 500


def test_create_reader_subsequent_call_different_chunk_size():
    """Verify subsequent call with chunk_size=1000 returns a TextReader with chunk_size == 1000 rather than cached 500."""
    reader1 = ReaderFactory.create_reader("text", chunk_size=500)
    assert isinstance(reader1, TextReader)
    assert reader1.chunk_size == 500

    reader2 = ReaderFactory.create_reader("text", chunk_size=1000)
    assert isinstance(reader2, TextReader)
    assert reader2.chunk_size == 1000
    assert reader1 is not reader2


def test_create_reader_mutable_attributes_independence():
    """Verify modifying attributes on one created reader does not mutate another instance."""
    reader1 = ReaderFactory.create_reader("text")
    reader2 = ReaderFactory.create_reader("text")

    assert reader1 is not reader2
    reader1.chunk_size = 999
    assert reader2.chunk_size != 999

    # Also verify independence when created with kwargs
    reader3 = ReaderFactory.create_reader("text", chunk_size=500)
    reader4 = ReaderFactory.create_reader("text", chunk_size=500)
    assert reader3 is not reader4

    reader3.chunk_size = 750
    assert reader4.chunk_size == 500
