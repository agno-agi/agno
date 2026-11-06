import asyncio

import pytest

from agno.knowledge.chunking.strategy import ChunkingStrategy
from agno.knowledge.document.base import Document
from agno.knowledge.reader.website_reader import WebsiteReader


class AsyncOnlyChunking(ChunkingStrategy):
    """Chunking strategy that only implements the async path."""

    def chunk(self, document):
        raise AssertionError("Async reading must not call synchronous chunking")

    async def achunk(self, document):
        await asyncio.sleep(0)
        return [
            Document(
                name=document.name,
                content=line,
                meta_data=document.meta_data.copy(),
            )
            for line in document.content.splitlines()
        ]


def _fake_crawl(monkeypatch, reader, content="first line\nsecond line"):
    async def _async_crawl(url: str, starting_depth: int = 1):
        return {"https://example.com/page": content}

    monkeypatch.setattr(reader, "async_crawl", _async_crawl)
    return reader


@pytest.mark.asyncio
async def test_async_read_awaits_async_chunking(monkeypatch):
    reader = _fake_crawl(monkeypatch, WebsiteReader(chunking_strategy=AsyncOnlyChunking()))

    documents = await reader.async_read("https://example.com", name="custom")

    assert [doc.content for doc in documents] == ["first line", "second line"]
    assert all(doc.name == "custom" for doc in documents)
    assert reader.chunk is True


@pytest.mark.asyncio
async def test_async_read_without_chunking_keeps_documents_whole(monkeypatch):
    reader = _fake_crawl(monkeypatch, WebsiteReader(chunk=False, chunking_strategy=AsyncOnlyChunking()))

    documents = await reader.async_read("https://example.com", name="custom")

    assert [doc.content for doc in documents] == ["first line\nsecond line"]
    assert reader.chunk is False
