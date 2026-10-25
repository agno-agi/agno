import io
from contextlib import ExitStack

import pytest

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


@pytest.mark.asyncio
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream_type", ["stringio", "text_file", "bytes_utf8", "bytes_latin1"])
async def test_read_text_and_binary_streams(tmp_path, use_async, stream_type):
    content = "# Guide\n\n中文 café\n" if stream_type != "bytes_latin1" else "# Guide\n\ncafé\n"
    with ExitStack() as stack:
        if stream_type == "text_file":
            path = tmp_path / "guide.md"
            path.write_text(content, encoding="utf-8")
            stream = stack.enter_context(path.open(encoding="utf-8"))
        elif stream_type == "stringio":
            stream = stack.enter_context(io.StringIO(content))
        else:
            encoding = "utf-8" if stream_type == "bytes_utf8" else "latin-1"
            stream = stack.enter_context(io.BytesIO(content.encode(encoding)))

        # Text streams are already decoded; the reader encoding applies only to bytes.
        reader = MarkdownReader(chunk=False, encoding=None if stream_type == "bytes_utf8" else "latin-1")
        stream.read(1)
        if use_async:
            documents = await reader.async_read(stream, name="guide")
        else:
            documents = reader.read(stream, name="guide")

        assert len(documents) == 1
        assert documents[0].content == content
        assert documents[0].name == "guide"
        assert not stream.closed
