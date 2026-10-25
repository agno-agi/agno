from io import BytesIO, StringIO

import pytest

from agno.knowledge.reader.markdown_reader import MarkdownReader
from agno.knowledge.reader.text_reader import TextReader


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_cls, default_name", [(TextReader, "text_file"), (MarkdownReader, "file")])
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("name", [None, "override.txt"])
async def test_read_stream_opened_from_file_descriptor(tmp_path, reader_cls, default_name, use_async, name):
    content = "# Notes\n\ncafé 中文\n"
    path = tmp_path / "notes.txt"
    path.write_bytes(content.encode("utf-8"))
    reader = reader_cls(chunk=False)

    with path.open("rb") as source, open(source.fileno(), "rb", closefd=False) as stream:
        assert isinstance(stream.name, int)
        stream.read(3)
        documents = await reader.async_read(stream, name=name) if use_async else reader.read(stream, name=name)
        assert not stream.closed

    assert len(documents) == 1
    assert documents[0].content == content
    assert documents[0].name == (name or default_name)


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_cls, default_name", [(TextReader, "text_file"), (MarkdownReader, "file")])
@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
@pytest.mark.parametrize("stream_type", [BytesIO, StringIO])
@pytest.mark.parametrize("stream_name", [None, 0, "notes.txt"])
async def test_read_stream_with_optional_name(reader_cls, default_name, use_async, stream_type, stream_name):
    content = "# Notes\n\ncafé 中文\n"
    data = content.encode("utf-8") if stream_type is BytesIO else content
    reader = reader_cls(chunk=False)

    with stream_type(data) as stream:
        stream.name = stream_name
        documents = await reader.async_read(stream) if use_async else reader.read(stream)
        assert not stream.closed

    assert len(documents) == 1
    assert documents[0].content == content
    assert documents[0].name == ("notes" if stream_name == "notes.txt" else default_name)
