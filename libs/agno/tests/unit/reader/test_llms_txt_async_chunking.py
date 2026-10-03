from unittest.mock import AsyncMock

import pytest

pytest.importorskip("bs4")

from agno.knowledge.chunking.strategy import ChunkingStrategy  # noqa: E402
from agno.knowledge.reader.llms_txt_reader import LLMsTxtReader  # noqa: E402


class RecordingChunker(ChunkingStrategy):
    def __init__(self):
        self.calls = []

    def chunk(self, document):
        self.calls.append("sync")
        return [document]

    async def achunk(self, document):
        self.calls.append("async")
        return [document]


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk", [True, False])
async def test_async_read_uses_async_chunker(monkeypatch, chunk):
    strategy = RecordingChunker()
    reader = LLMsTxtReader(chunk=chunk, chunking_strategy=strategy)
    fetch = AsyncMock(side_effect=["# Project\n## Docs\n- [Guide](/guide): Start here", "Guide content"])
    monkeypatch.setattr(reader, "async_fetch_url", fetch)

    documents = await reader.async_read("https://example.com/llms.txt")

    assert strategy.calls == (["async", "async"] if chunk else [])
    assert [doc.content for doc in documents] == ["# Project", "Guide content"]
    assert documents[1].meta_data["url"] == "https://example.com/guide"
    assert documents[1].meta_data["section"] == "Docs"


@pytest.mark.parametrize("chunk", [True, False])
def test_sync_read_keeps_sync_chunker(monkeypatch, chunk):
    strategy = RecordingChunker()
    reader = LLMsTxtReader(chunk=chunk, chunking_strategy=strategy)
    monkeypatch.setattr(reader, "fetch_url", lambda url: "# Project")

    assert reader.read("https://example.com/llms.txt")[0].content == "# Project"
    assert strategy.calls == (["sync"] if chunk else [])
