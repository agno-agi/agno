"""Tests URL ingestion which must respect Reader(chunk=...)"""

from typing import List, Optional

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document.base import Document
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType


class FakeUrlReader(Reader):
    """URL reader that returns a single whole document and honours self.chunk.

    Advertises ContentType.URL so the ingestion path skips network download and
    calls the reader with the URL directly."""

    @classmethod
    def get_supported_chunking_strategies(cls):
        from agno.knowledge.chunking.strategy import ChunkingStrategyType

        return [ChunkingStrategyType.FIXED_SIZE_CHUNKER]

    @classmethod
    def get_supported_content_types(cls):
        return [ContentType.URL]

    def _build_documents(self, name: Optional[str]) -> List[Document]:
        # Long enough that fixed-size chunking would split it into many pieces.
        content = "word " * 2000
        document = Document(name=name or "doc", id="doc-1", content=content)
        if self.chunk:
            return self.chunk_document(document)
        return [document]

    def read(self, obj, name=None, password=None) -> List[Document]:
        return self._build_documents(name)

    async def async_read(self, obj, name=None, password=None) -> List[Document]:
        return self._build_documents(name)


def _make_content(reader: Reader) -> Content:
    return Content(url="https://example.com/page", reader=reader)


def test_sync_url_ingestion_respects_chunk_false(knowledge, vector_db):
    """chunk=False -> the single whole document is inserted unchanged."""
    reader = FakeUrlReader(chunk=False)

    knowledge._load_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert len(vector_db.inserted_documents) == 1


@pytest.mark.asyncio
async def test_async_url_ingestion_respects_chunk_false(knowledge, vector_db):
    """Async path: chunk=False -> exactly one document inserted."""
    reader = FakeUrlReader(chunk=False)

    await knowledge._aload_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert len(vector_db.inserted_documents) == 1


def test_sync_url_ingestion_does_not_double_chunk_when_chunk_true(knowledge, vector_db):
    """chunk=True -> reader chunks once; URL path must not re-chunk on top of that."""

    reader = FakeUrlReader(chunk=True)
    expected = len(reader.read("https://example.com/page", name="doc"))

    knowledge._load_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert expected > 1  # sanity: the content really is chunkable
    assert len(vector_db.inserted_documents) == expected


@pytest.mark.asyncio
async def test_async_url_ingestion_does_not_double_chunk_when_chunk_true(knowledge, vector_db):
    """Async path: chunk=True -> reader chunks once; no extra chunking on top."""

    reader = FakeUrlReader(chunk=True)
    expected = len(await reader.async_read("https://example.com/page", name="doc"))

    await knowledge._aload_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert expected > 1
    assert len(vector_db.inserted_documents) == expected
