"""Per-upload chunker options must not leak into the knowledge base's reader."""

import pytest

from agno.knowledge.content import Content, FileData
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.text_reader import TextReader
from agno.os.routers.knowledge.knowledge import process_content


def _content():
    return Content(
        name="a.txt",
        file_data=FileData(content=b"hello", type="text/plain", filename="a.txt"),
    )


@pytest.mark.asyncio
async def test_upload_chunker_does_not_mutate_the_knowledge_base_reader(monkeypatch):
    reader = TextReader(name="notes")
    knowledge = Knowledge(name="docs", readers={"notes": reader})
    content = _content()
    original_chunk_size = reader.chunking_strategy.chunk_size

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "_aload_content", _noop)

    await process_content(knowledge, content, "notes", "FixedSizeChunker", 1000, 0)

    # This upload used the requested chunking ...
    assert content.reader.chunking_strategy.chunk_size == 1000
    # ... but the knowledge base's own reader is unchanged for later uploads.
    assert reader.chunking_strategy.chunk_size == original_chunk_size


@pytest.mark.asyncio
async def test_upload_chunker_does_not_replace_the_resolved_default_reader(monkeypatch):
    knowledge = Knowledge(name="docs")
    text_reader = knowledge.text_reader
    content = Content(
        name="a.txt",
        file_data=FileData(content=b"hello", type="text/plain", filename="a.txt"),
        reader=text_reader,
    )
    original_chunk_size = text_reader.chunking_strategy.chunk_size

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr(knowledge, "_aload_content", _noop)

    await process_content(knowledge, content, None, "FixedSizeChunker", 512, 0)

    assert content.reader.chunking_strategy.chunk_size == 512
    assert text_reader.chunking_strategy.chunk_size == original_chunk_size
