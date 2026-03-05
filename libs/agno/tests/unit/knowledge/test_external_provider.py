"""Tests for ExternalKnowledgeProvider protocol and integration."""

from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.content import Content, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.external_provider import ExternalKnowledgeProvider
from agno.knowledge.external_provider.lightrag import LightRagProvider
from agno.knowledge.external_provider.schemas import ProcessingResult
from agno.knowledge.knowledge import Knowledge
from agno.knowledge.pipeline.ingestion import KnowledgeContentOrigin
from agno.vectordb.base import VectorDb

# ------------------------------------------------------------------
# Mock implementations
# ------------------------------------------------------------------


class MockExternalProvider:
    """A mock that satisfies the ExternalKnowledgeProvider protocol."""

    def __init__(self):
        self.ingested_files: List[str] = []
        self.ingested_texts: List[str] = []
        self.queries: List[str] = []
        self.deleted_ids: List[str] = []
        self._status_responses: Dict[str, ProcessingResult] = {}

    def ingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        self.ingested_files.append(filename or "unknown")
        pid = f"proc-file-{len(self.ingested_files)}"
        return ProcessingResult(processing_id=pid, status=ContentStatus.PROCESSING)

    async def aingest_file(
        self,
        file_content: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        self.ingested_files.append(filename or "unknown")
        pid = f"proc-file-{len(self.ingested_files)}"
        return ProcessingResult(processing_id=pid, status=ContentStatus.PROCESSING)

    def ingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        self.ingested_texts.append(source_name or "unknown")
        pid = f"proc-text-{len(self.ingested_texts)}"
        return ProcessingResult(processing_id=pid, status=ContentStatus.PROCESSING)

    async def aingest_text(
        self,
        text: str,
        source_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProcessingResult:
        self.ingested_texts.append(source_name or "unknown")
        pid = f"proc-text-{len(self.ingested_texts)}"
        return ProcessingResult(processing_id=pid, status=ContentStatus.PROCESSING)

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

    def get_status(self, processing_id: str) -> ProcessingResult:
        if processing_id in self._status_responses:
            return self._status_responses[processing_id]
        return ProcessingResult(processing_id=processing_id, status=ContentStatus.PROCESSING)

    async def aget_status(self, processing_id: str) -> ProcessingResult:
        return self.get_status(processing_id)


class MockVectorDb(VectorDb):
    """A regular VectorDb that does NOT satisfy ExternalKnowledgeProvider."""

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
    def test_mock_provider_satisfies_protocol(self):
        provider = MockExternalProvider()
        assert isinstance(provider, ExternalKnowledgeProvider)

    def test_lightrag_provider_satisfies_protocol(self):
        provider = LightRagProvider()
        assert isinstance(provider, ExternalKnowledgeProvider)

    def test_regular_vectordb_does_not_satisfy_protocol(self):
        vdb = MockVectorDb()
        assert not isinstance(vdb, ExternalKnowledgeProvider)


# ------------------------------------------------------------------
# Knowledge external_provider field tests
# ------------------------------------------------------------------


class TestKnowledgeExternalProvider:
    def test_regular_vectordb_no_external_provider(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        assert knowledge.external_provider is None

    def test_external_provider_not_passed_to_pipeline_when_regular_vdb(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        assert knowledge._pipeline.external_provider is None

    def test_external_provider_passed_to_pipeline(self):
        provider = MockExternalProvider()
        knowledge = Knowledge(external_provider=provider)
        assert knowledge._pipeline.external_provider is provider


# ------------------------------------------------------------------
# Search routing tests
# ------------------------------------------------------------------


class TestSearchRouting:
    def test_search_routes_to_regular_vectordb(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        results = knowledge.search("test query")
        assert len(results) == 1
        assert results[0].content == "regular-result"

    def test_search_routes_to_external_provider(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        knowledge.external_provider = provider

        results = knowledge.search("test query")
        assert len(results) == 1
        assert "test query" in results[0].content
        assert len(provider.queries) == 1

    @pytest.mark.asyncio
    async def test_asearch_routes_to_external_provider(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        knowledge.external_provider = provider

        results = await knowledge.asearch("async query")
        assert len(results) == 1
        assert "async query" in results[0].content
        assert len(provider.queries) == 1


# ------------------------------------------------------------------
# Delete routing tests
# ------------------------------------------------------------------


class TestDeleteRouting:
    def test_delete_routes_to_external_provider(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        knowledge.external_provider = provider

        # Mock content store to return content with external_id
        mock_content = Content(name="test", external_id="ext-123")
        knowledge._content_store.get_content_by_id = MagicMock(return_value=mock_content)
        knowledge._content_store.contents_db = None
        knowledge.contents_db = None

        knowledge.remove_content_by_id("content-1")
        assert "ext-123" in provider.deleted_ids

    @pytest.mark.asyncio
    async def test_adelete_routes_to_external_provider(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        knowledge.external_provider = provider

        mock_content = Content(name="test", external_id="ext-456")
        knowledge._content_store.aget_content_by_id = AsyncMock(return_value=mock_content)
        knowledge._content_store.contents_db = None
        knowledge.contents_db = None

        await knowledge.aremove_content_by_id("content-2")
        assert "ext-456" in provider.deleted_ids

    def test_delete_regular_vectordb_uses_content_id(self):
        vdb = MockVectorDb()
        vdb.delete_by_content_id = MagicMock(return_value=True)
        knowledge = Knowledge(vector_db=vdb)
        knowledge.contents_db = None

        knowledge.remove_content_by_id("content-3")
        vdb.delete_by_content_id.assert_called_once_with("content-3")


# ------------------------------------------------------------------
# Pipeline external ingestion tests
# ------------------------------------------------------------------


class TestPipelineExternalIngestion:
    def test_ingest_external_content_type(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        pipeline = knowledge._pipeline
        pipeline.external_provider = provider
        pipeline.content_store.insert = MagicMock()
        pipeline.content_store.update = MagicMock()

        content = Content(
            name="test.txt",
            file_data=FileData(content=b"hello world", type="text/plain", filename="test.txt"),
        )
        pipeline._ingest_external(content, KnowledgeContentOrigin.CONTENT)

        assert len(provider.ingested_files) == 1
        assert content.status == ContentStatus.PROCESSING
        assert content.processing_id is not None

    def test_ingest_external_topic(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        pipeline = knowledge._pipeline
        pipeline.external_provider = provider
        pipeline.content_store.insert = MagicMock()
        pipeline.content_store.update = MagicMock()

        mock_reader = MagicMock()
        mock_reader.read = MagicMock(return_value=[Document(content="topic content")])

        content = Content(name="topic1", topics=["topic1"], reader=mock_reader)
        pipeline._ingest_external(content, KnowledgeContentOrigin.TOPIC)

        assert len(provider.ingested_texts) == 1
        assert content.status == ContentStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_aingest_external_content_type(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        pipeline = knowledge._pipeline
        pipeline.external_provider = provider
        pipeline.content_store.ainsert = AsyncMock()
        pipeline.content_store.aupdate = AsyncMock()

        content = Content(
            name="test.txt",
            file_data=FileData(content=b"hello world", type="text/plain", filename="test.txt"),
        )
        await pipeline._aingest_external(content, KnowledgeContentOrigin.CONTENT)

        assert len(provider.ingested_files) == 1
        assert content.status == ContentStatus.PROCESSING
        assert content.processing_id is not None

    def test_ingest_external_failure_sets_status(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        provider.ingest_file = MagicMock(side_effect=Exception("Upload failed"))
        pipeline = knowledge._pipeline
        pipeline.external_provider = provider
        pipeline.content_store.insert = MagicMock()
        pipeline.content_store.update = MagicMock()

        content = Content(
            name="test.txt",
            file_data=FileData(content=b"hello world", type="text/plain", filename="test.txt"),
        )
        pipeline._ingest_external(content, KnowledgeContentOrigin.CONTENT)

        assert content.status == ContentStatus.FAILED
        assert "Upload failed" in (content.status_message or "")


# ------------------------------------------------------------------
# Status resolution tests
# ------------------------------------------------------------------


class TestStatusResolution:
    def test_resolve_external_status_completed(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        provider._status_responses["proc-123"] = ProcessingResult(
            processing_id="proc-123",
            external_id="doc-456",
            status=ContentStatus.COMPLETED,
        )
        knowledge.external_provider = provider

        mock_content = Content(
            id="content-1",
            name="test",
            processing_id="proc-123",
            status=ContentStatus.PROCESSING,
        )
        knowledge._content_store.get_content_by_id = MagicMock(return_value=mock_content)
        knowledge._content_store.update = MagicMock()

        status, message = knowledge._resolve_external_status("content-1", ContentStatus.PROCESSING, None)
        assert status == ContentStatus.COMPLETED
        assert mock_content.external_id == "doc-456"
        knowledge._content_store.update.assert_called_once()

    def test_resolve_external_status_failed(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        provider._status_responses["proc-789"] = ProcessingResult(
            processing_id="proc-789",
            status=ContentStatus.FAILED,
            status_message="External provider processing failed",
        )
        knowledge.external_provider = provider

        mock_content = Content(
            id="content-2",
            name="test",
            processing_id="proc-789",
            status=ContentStatus.PROCESSING,
        )
        knowledge._content_store.get_content_by_id = MagicMock(return_value=mock_content)
        knowledge._content_store.update = MagicMock()

        status, message = knowledge._resolve_external_status("content-2", ContentStatus.PROCESSING, None)
        assert status == ContentStatus.FAILED
        assert message == "External provider processing failed"
        knowledge._content_store.update.assert_called_once()

    def test_resolve_external_status_still_processing(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        knowledge.external_provider = provider

        mock_content = Content(
            id="content-3",
            name="test",
            processing_id="proc-still",
            status=ContentStatus.PROCESSING,
        )
        knowledge._content_store.get_content_by_id = MagicMock(return_value=mock_content)
        knowledge._content_store.update = MagicMock()

        status, message = knowledge._resolve_external_status("content-3", ContentStatus.PROCESSING, None)
        assert status == ContentStatus.PROCESSING
        # Should NOT persist when still processing
        knowledge._content_store.update.assert_not_called()

    def test_resolve_external_status_no_processing_id(self):
        """Falls back to external_id when processing_id is None."""
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        provider._status_responses["ext-fallback"] = ProcessingResult(
            processing_id="ext-fallback",
            status=ContentStatus.COMPLETED,
            external_id="ext-fallback",
        )
        knowledge.external_provider = provider

        mock_content = Content(
            id="content-4",
            name="test",
            external_id="ext-fallback",
            status=ContentStatus.PROCESSING,
        )
        knowledge._content_store.get_content_by_id = MagicMock(return_value=mock_content)
        knowledge._content_store.update = MagicMock()

        status, _ = knowledge._resolve_external_status("content-4", ContentStatus.PROCESSING, None)
        assert status == ContentStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_aresolve_external_status_completed(self):
        knowledge = Knowledge(vector_db=MockVectorDb())
        provider = MockExternalProvider()
        provider._status_responses["proc-async"] = ProcessingResult(
            processing_id="proc-async",
            external_id="doc-async",
            status=ContentStatus.COMPLETED,
        )
        knowledge.external_provider = provider

        mock_content = Content(
            id="content-5",
            name="test",
            processing_id="proc-async",
            status=ContentStatus.PROCESSING,
        )
        knowledge._content_store.aget_content_by_id = AsyncMock(return_value=mock_content)
        knowledge._content_store.aupdate = AsyncMock()

        status, message = await knowledge._aresolve_external_status("content-5", ContentStatus.PROCESSING, None)
        assert status == ContentStatus.COMPLETED
        assert mock_content.external_id == "doc-async"
        knowledge._content_store.aupdate.assert_called_once()
