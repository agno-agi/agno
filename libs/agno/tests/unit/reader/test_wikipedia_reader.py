import asyncio

import pytest

pytest.importorskip("wikipedia")

from agno.knowledge.chunking.fixed import FixedSizeChunking
from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document import Document
from agno.knowledge.reader import wikipedia_reader
from agno.knowledge.reader.wikipedia_reader import WikipediaReader


class SyncLineChunking(ChunkingStrategy):
    def chunk(self, document):
        return [
            Document(name=document.name, meta_data=document.meta_data, content=line)
            for line in document.content.splitlines()
        ]


class AsyncLineChunking(SyncLineChunking):
    def chunk(self, document):
        raise RuntimeError("Use the asynchronous chunking implementation")

    async def achunk(self, document):
        await asyncio.sleep(0)
        return super().chunk(document)


def test_wikipedia_reader_chunk_size_propagation():
    """Test that chunk_size is propagated to default chunking strategy"""
    reader = WikipediaReader(chunk_size=550)
    assert reader.chunk_size == 550
    assert reader.chunking_strategy.chunk_size == 550
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)


def test_wikipedia_reader_default_chunk_size():
    """Test default chunk_size is 5000"""
    reader = WikipediaReader()
    assert reader.chunk_size == 5000
    assert reader.chunking_strategy.chunk_size == 5000
    assert isinstance(reader.chunking_strategy, FixedSizeChunking)


@pytest.mark.asyncio
async def test_async_read_uses_async_chunking(monkeypatch):
    monkeypatch.setattr(
        wikipedia_reader.wikipedia,
        "summary",
        lambda topic, auto_suggest: "first line\nsecond line",
    )
    reader = WikipediaReader(chunking_strategy=AsyncLineChunking())

    documents = await reader.async_read("Async chunking")

    assert [doc.content for doc in documents] == ["first line", "second line"]
    assert all(doc.name == "Async chunking" for doc in documents)
    assert all(doc.meta_data == {"topic": "Async chunking"} for doc in documents)


@pytest.mark.asyncio
async def test_async_read_supports_sync_only_chunking(monkeypatch):
    monkeypatch.setattr(
        wikipedia_reader.wikipedia,
        "summary",
        lambda topic, auto_suggest: "first line\nsecond line",
    )
    reader = WikipediaReader(chunking_strategy=SyncLineChunking())

    documents = await reader.async_read("Sync fallback")

    assert [doc.content for doc in documents] == ["first line", "second line"]
    assert all(doc.name == "Sync fallback" for doc in documents)
