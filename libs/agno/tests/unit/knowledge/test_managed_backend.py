"""Tests for ManagedKnowledgeBackend protocol and integration."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.content import Content, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.managed_backend import ManagedKnowledgeBackend
from agno.knowledge.managed_backend.lightrag import LightRagBackend
from agno.knowledge.pipeline.ingestion import KnowledgeContentOrigin
from agno.vectordb.base import VectorDb

# ------------------------------------------------------------------
# Mock implementations
# ------------------------------------------------------------------


class MockManagedBackend:
    """A mock that satisfies the ManagedKnowledgeBackend protocol."""

    def __init__(self):
        self.ingested_files: List[str] = []
        self.ingested_texts: List[str] = []
        self.queries: List[str] = []
        self.deleted_ids: List[str] = []

    def ingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        self.ingested_files.append(filename or "unknown")
        return f"ext-file-{len(self.ingested_files)}"

    async def aingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        self.ingested_files.append(filename or "unknown")
        return f"ext-file-{len(self.ingested_files)}"

    def ingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        self.ingested_texts.append(source_name or "unknown")
        return f"ext-text-{len(self.ingested_texts)}"

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        self.ingested_texts.append(source_name or "unknown")
        return f"ext-text-{len(self.ingested_texts)}"

    def query(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        self.queries.append(query)
        return [Document(content=f"Result for: {query}", meta_data={"source": "mock"})]

    async def aquery(
        self,
        query: str,
        limit: int = 10,
        mode: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        self.queries.append(query)
        return [Document(content=f"Result for: {query}", meta_data={"source": "mock"})]

    def delete_content(self, external_id: str) -> bool:
        self.deleted_ids.append(external_id)
        return True

    async def adelete_content(self, external_id: str) -> bool:
        self.deleted_ids.append(external_id)
        return True


class MockVectorDb(VectorDb):
    """A regular VectorDb that does NOT satisfy ManagedKnowledgeBackend."""

    def create(self) -> None:
        pass

    async def async_create(self) -> None:
        pass

    def name_exists(self, name: str) -> bool:
        return False

    async def async_name_exists(self, name: str) -> bool:
        return False

    def id_exists(self, id: str) -> bool:
        return False

    def content_hash_exists(self, content_hash: str) -> bool:
        return False

    def insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return [Document(content="regular-result")]

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        return [Document(content="regular-result")]

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

    def update_metadata(self, content_id: str, metadata) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


# ------------------------------------------------------------------
# Protocol detection tests
# ------------------------------------------------------------------


class TestProtocolDetection:
    def test_mock_backend_satisfies_protocol(self):
        backend = MockManagedBackend()
        assert isinstance(backend, ManagedKnowledgeBackend)

    def test_lightrag_backend_satisfies_protocol(self):
        backend = LightRagBackend()
        assert isinstance(backend, ManagedKnowledgeBackend)

    def test_regular_vectordb_does_not_satisfy_protocol(self):
        vdb = MockVectorDb()
        assert not isinstance(vdb, ManagedKnowledgeBackend)

    def test_lightrag_vectordb_satisfies_protocol(self):
        from agno.vectordb.lightrag import LightRag

        lightrag = LightRag.__new__(LightRag)
        # Need to set up minimal state for isinstance check
        lightrag._backend = LightRagBackend()
        assert isinstance(lightrag, ManagedKnowledgeBackend)


# ------------------------------------------------------------------
# Knowledge auto-detection tests
# ------------------------------------------------------------------


class TestKnowledgeAutoDetection:
    def test_regular_vectordb_no_managed_backend(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        assert knowledge._managed_backend is None

    def test_managed_backend_not_passed_to_pipeline_when_regular_vdb(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        assert knowledge._pipeline.managed_backend is None


# ------------------------------------------------------------------
# Search routing tests
# ------------------------------------------------------------------


class TestSearchRouting:
    def test_search_routes_to_regular_vectordb(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        results = knowledge.search("test query")
        assert len(results) == 1
        assert results[0].content == "regular-result"

    def test_search_routes_to_managed_backend(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        knowledge._managed_backend = backend

        results = knowledge.search("test query")
        assert len(results) == 1
        assert "test query" in results[0].content
        assert len(backend.queries) == 1

    @pytest.mark.asyncio
    async def test_asearch_routes_to_managed_backend(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        knowledge._managed_backend = backend

        results = await knowledge.asearch("async query")
        assert len(results) == 1
        assert "async query" in results[0].content
        assert len(backend.queries) == 1


# ------------------------------------------------------------------
# Delete routing tests
# ------------------------------------------------------------------


class TestDeleteRouting:
    def test_delete_routes_to_managed_backend(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        knowledge._managed_backend = backend

        # Mock content store to return content with external_id
        mock_content = Content(name="test", external_id="ext-123")
        knowledge._content_store.get_content_by_id = MagicMock(return_value=mock_content)
        knowledge._content_store.contents_db = None
        knowledge.contents_db = None

        knowledge.remove_content_by_id("content-1")
        assert "ext-123" in backend.deleted_ids

    @pytest.mark.asyncio
    async def test_adelete_routes_to_managed_backend(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        knowledge._managed_backend = backend

        mock_content = Content(name="test", external_id="ext-456")
        knowledge._content_store.aget_content_by_id = AsyncMock(return_value=mock_content)
        knowledge._content_store.contents_db = None
        knowledge.contents_db = None

        await knowledge.aremove_content_by_id("content-2")
        assert "ext-456" in backend.deleted_ids

    def test_delete_regular_vectordb_uses_content_id(self):
        vdb = MockVectorDb()
        vdb.delete_by_content_id = MagicMock(return_value=True)
        knowledge = Knowledge(vector_db=vdb)
        knowledge.contents_db = None

        knowledge.remove_content_by_id("content-3")
        vdb.delete_by_content_id.assert_called_once_with("content-3")


# ------------------------------------------------------------------
# Pipeline managed ingestion tests
# ------------------------------------------------------------------


class TestPipelineManagedIngestion:
    def test_ingest_managed_content_type(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        pipeline = knowledge._pipeline
        pipeline.managed_backend = backend
        pipeline.content_store.insert = MagicMock()
        pipeline.content_store.update = MagicMock()

        content = Content(
            name="test.txt",
            file_data=FileData(content=b"hello world", type="text/plain", filename="test.txt"),
        )
        pipeline._ingest_managed(content, KnowledgeContentOrigin.CONTENT)

        assert len(backend.ingested_files) == 1
        assert content.status == ContentStatus.COMPLETED
        assert content.external_id is not None

    def test_ingest_managed_topic(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        pipeline = knowledge._pipeline
        pipeline.managed_backend = backend
        pipeline.content_store.insert = MagicMock()
        pipeline.content_store.update = MagicMock()

        mock_reader = MagicMock()
        mock_reader.read = MagicMock(return_value=[Document(content="topic content")])

        content = Content(name="topic1", topics=["topic1"], reader=mock_reader)
        pipeline._ingest_managed(content, KnowledgeContentOrigin.TOPIC)

        assert len(backend.ingested_texts) == 1
        assert content.status == ContentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_aingest_managed_content_type(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        pipeline = knowledge._pipeline
        pipeline.managed_backend = backend
        pipeline.content_store.ainsert = AsyncMock()
        pipeline.content_store.aupdate = AsyncMock()

        content = Content(
            name="test.txt",
            file_data=FileData(content=b"hello world", type="text/plain", filename="test.txt"),
        )
        await pipeline._aingest_managed(content, KnowledgeContentOrigin.CONTENT)

        assert len(backend.ingested_files) == 1
        assert content.status == ContentStatus.COMPLETED
        assert content.external_id is not None

    def test_ingest_managed_failure_sets_status(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        backend = MockManagedBackend()
        backend.ingest_file = MagicMock(side_effect=Exception("Upload failed"))
        pipeline = knowledge._pipeline
        pipeline.managed_backend = backend
        pipeline.content_store.insert = MagicMock()
        pipeline.content_store.update = MagicMock()

        content = Content(
            name="test.txt",
            file_data=FileData(content=b"hello world", type="text/plain", filename="test.txt"),
        )
        pipeline._ingest_managed(content, KnowledgeContentOrigin.CONTENT)

        assert content.status == ContentStatus.FAILED
        assert "Upload failed" in (content.status_message or "")
