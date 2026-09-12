import asyncio
from io import BytesIO

import pytest

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.knowledge.reader.markdown_reader import MarkdownReader
from agno.knowledge.reader.text_reader import TextReader


class SyncLineChunking(ChunkingStrategy):
    def chunk(self, document):
        return [Document(name=document.name, content=line) for line in document.content.splitlines()]


class AsyncLineChunking(SyncLineChunking):
    def chunk(self, document):
        raise RuntimeError("Use the asynchronous chunking implementation")

    async def achunk(self, document):
        await asyncio.sleep(0)
        return super().chunk(document)


@pytest.fixture(params=["path", "stream"])
def text_source(request, tmp_path):
    content = "first line\nsecond line"
    if request.param == "path":
        path = tmp_path / "example.txt"
        path.write_text(content, encoding="utf-8")
        yield path
    else:
        with BytesIO(content.encode("utf-8")) as stream:
            yield stream


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_cls", [TextReader, MarkdownReader])
@pytest.mark.parametrize("chunk", [True, False])
async def test_async_read_uses_async_chunking(reader_cls, text_source, chunk):
    reader = reader_cls(chunk=chunk, chunking_strategy=AsyncLineChunking())

    documents = await reader.async_read(text_source, name="example")

    expected = ["first line", "second line"] if chunk else ["first line\nsecond line"]
    assert [doc.content for doc in documents] == expected
    assert all(doc.name == "example" for doc in documents)


@pytest.mark.asyncio
@pytest.mark.parametrize("reader_cls", [TextReader, MarkdownReader])
async def test_async_read_supports_sync_only_chunking(reader_cls, text_source):
    reader = reader_cls(chunking_strategy=SyncLineChunking())

    documents = await reader.async_read(text_source, name="example")

    assert [doc.content for doc in documents] == ["first line", "second line"]
    assert all(doc.name == "example" for doc in documents)
