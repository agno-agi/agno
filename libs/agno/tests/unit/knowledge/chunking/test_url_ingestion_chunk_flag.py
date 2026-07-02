"""Tests URL ingestion which must respect Reader(chunk=...)"""

from typing import List, Optional

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document.base import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.reader.base import Reader
from agno.knowledge.types import ContentType
from agno.vectordb.base import VectorDb


class CapturingVectorDb(VectorDb):
    """VectorDb stub that records the documents handed to insert/upsert."""

    def __init__(self):
        self.inserted_documents: List[Document] = []

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    async def async_insert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    async def async_upsert(self, content_hash: str, documents, filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert_available(self) -> bool:
        return False

    def search(self, query: str, limit: int = 5, filters=None):
        return []

    async def async_search(self, query: str, limit: int = 5, filters=None):
        return []

    def drop(self) -> None:
        pass

    async def async_drop(self) -> None:
        pass

    def exists(self) -> bool:
        return True

    async def async_exists(self) -> bool:
        return True

    def delete(self) -> bool:
        return True

    def delete_by_id(self, id: str) -> bool:
        return True

    def delete_by_name(self, name: str) -> bool:
        return True

    def delete_by_metadata(self, metadata) -> bool:
        return True

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def get_supported_search_types(self):
        return ["vector"]


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


def test_sync_url_ingestion_respects_chunk_false():
    """chunk=False -> the single whole document is inserted unchanged."""
    vector_db = CapturingVectorDb()
    knowledge = Knowledge(vector_db=vector_db)
    reader = FakeUrlReader(chunk=False)

    knowledge._load_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert len(vector_db.inserted_documents) == 1


@pytest.mark.asyncio
async def test_async_url_ingestion_respects_chunk_false():
    """Async path: chunk=False -> exactly one document inserted."""
    vector_db = CapturingVectorDb()
    knowledge = Knowledge(vector_db=vector_db)
    reader = FakeUrlReader(chunk=False)

    await knowledge._aload_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert len(vector_db.inserted_documents) == 1


def test_sync_url_ingestion_does_not_double_chunk_when_chunk_true():
    """chunk=True -> reader chunks once; URL path must not re-chunk on top of that."""
    vector_db = CapturingVectorDb()
    knowledge = Knowledge(vector_db=vector_db)

    reader = FakeUrlReader(chunk=True)
    expected = len(reader.read("https://example.com/page", name="doc"))

    knowledge._load_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert expected > 1  # sanity: the content really is chunkable
    assert len(vector_db.inserted_documents) == expected


@pytest.mark.asyncio
async def test_async_url_ingestion_does_not_double_chunk_when_chunk_true():
    """Async path: chunk=True -> reader chunks once; no extra chunking on top."""
    vector_db = CapturingVectorDb()
    knowledge = Knowledge(vector_db=vector_db)

    reader = FakeUrlReader(chunk=True)
    expected = len(await reader.async_read("https://example.com/page", name="doc"))

    await knowledge._aload_from_url(_make_content(reader), upsert=False, skip_if_exists=False)

    assert expected > 1
    assert len(vector_db.inserted_documents) == expected
