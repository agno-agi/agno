import asyncio
import json
from io import BytesIO

import pytest

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.knowledge.reader.json_reader import JSONReader


class AsyncOnlyChunking(ChunkingStrategy):
    def chunk(self, document):
        raise AssertionError("Async reading must not call synchronous chunking")

    async def achunk(self, document):
        await asyncio.sleep(0)
        return [
            Document(
                name=document.name,
                content=f"{document.content}:{index}",
                meta_data=document.meta_data.copy(),
            )
            for index in range(2)
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["path", "stream"])
async def test_async_read_awaits_chunking_and_preserves_order(tmp_path, source):
    data = [{"key": "first"}, {"key": "second"}]
    content = json.dumps(data).encode()
    if source == "path":
        path = tmp_path / "data.json"
        path.write_bytes(content)
    else:
        path = BytesIO(content)
    reader = JSONReader(chunking_strategy=AsyncOnlyChunking())

    documents = await reader.async_read(path, name="custom")

    assert [doc.content for doc in documents] == [f"{json.dumps(item)}:{index}" for item in data for index in range(2)]
    assert [doc.meta_data["page"] for doc in documents] == [1, 1, 2, 2]
    assert all(doc.name == "custom" for doc in documents)
    assert reader.chunk is True
    if source == "stream":
        assert not path.closed


@pytest.mark.asyncio
async def test_async_read_without_chunking_keeps_documents_whole():
    reader = JSONReader(chunk=False, chunking_strategy=AsyncOnlyChunking())
    data = [{"key": "first"}, {"key": "second"}]

    documents = await reader.async_read(BytesIO(json.dumps(data).encode()))

    assert [json.loads(doc.content) for doc in documents] == data
    assert reader.chunk is False


@pytest.mark.asyncio
async def test_async_read_propagates_chunking_error():
    class FailingChunking(AsyncOnlyChunking):
        async def achunk(self, document):
            raise RuntimeError("chunking failed")

    reader = JSONReader(chunking_strategy=FailingChunking())
    with pytest.raises(RuntimeError, match="chunking failed"):
        await reader.async_read(BytesIO(b'{"key": "value"}'))


def test_read_logs_chunking_error(mocker):
    class FailingSyncChunking(ChunkingStrategy):
        def chunk(self, document):
            raise RuntimeError("chunking failed")

    log_error = mocker.patch("agno.knowledge.reader.json_reader.log_error")
    reader = JSONReader(chunking_strategy=FailingSyncChunking())

    with pytest.raises(RuntimeError, match="chunking failed"):
        reader.read(BytesIO(b'{"key": "value"}'))

    assert log_error.call_count == 1
    assert "chunking failed" in log_error.call_args.args[0]


@pytest.mark.asyncio
async def test_async_read_logs_chunking_error(mocker):
    class FailingChunking(AsyncOnlyChunking):
        async def achunk(self, document):
            raise RuntimeError("chunking failed")

    log_error = mocker.patch("agno.knowledge.reader.json_reader.log_error")
    reader = JSONReader(chunking_strategy=FailingChunking())

    with pytest.raises(RuntimeError, match="chunking failed"):
        await reader.async_read(BytesIO(b'{"key": "value"}'))

    assert log_error.call_count == 1
    assert "chunking failed" in log_error.call_args.args[0]
