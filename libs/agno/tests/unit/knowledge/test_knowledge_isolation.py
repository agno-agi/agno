"""Tests for knowledge instance isolation features.

Tests that knowledge instances with isolate_vector_search=True filter by linked_to.
"""

from typing import Any, Dict, List

import pytest

from agno.knowledge.content import Content
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Mock VectorDb that tracks search calls and their filters."""

    def __init__(self):
        self.search_calls: List[Dict[str, Any]] = []
        self.inserted_documents: List[Document] = []

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
        self.inserted_documents.extend(documents)

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.inserted_documents.extend(documents)

    def upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        pass

    def upsert_available(self) -> bool:
        return True

    def search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        self.search_calls.append({"query": query, "limit": limit, "filters": filters})
        return [Document(name="test", content="test content")]

    async def async_search(self, query: str, limit: int = 5, filters=None) -> List[Document]:
        self.search_calls.append({"query": query, "limit": limit, "filters": filters})
        return [Document(name="test", content="test content")]

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

    def delete_by_metadata(self, metadata: Dict[str, Any]) -> bool:
        return True

    def update_metadata(self, content_id: str, metadata: Dict[str, Any]) -> None:
        pass

    def delete_by_content_id(self, content_id: str) -> bool:
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


class TestKnowledgeIsolation:
    """Tests for knowledge isolation based on isolate_vector_search flag."""

    def test_search_with_isolation_enabled_injects_filter(self):
        """Test that search with isolate_vector_search=True injects linked_to filter."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Test KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        knowledge.search("test query")

        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] == {"linked_to": "Test KB"}

    def test_search_without_isolation_no_filter(self):
        """Test that search without isolate_vector_search does not inject filter (backwards compatible)."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Test KB",
            vector_db=mock_db,
            # isolate_vector_search defaults to False
        )

        knowledge.search("test query")

        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] is None

    def test_search_without_name_no_filter(self):
        """Test that search without name does not inject filter even with isolation enabled."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        knowledge.search("test query")

        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] is None

    def test_search_with_isolation_merges_existing_dict_filters(self):
        """Test that linked_to filter merges with existing dict filters when isolation enabled."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Test KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        knowledge.search("test query", filters={"category": "docs"})

        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] == {"category": "docs", "linked_to": "Test KB"}

    def test_search_with_isolation_list_filters_injects_linked_to(self):
        """Test that linked_to filter is auto-injected for list-based FilterExpr filters."""
        from agno.filters import EQ

        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Test KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        list_filters = [EQ("category", "docs")]

        knowledge.search("test query", filters=list_filters)

        assert len(mock_db.search_calls) == 1
        result_filters = mock_db.search_calls[0]["filters"]
        assert len(result_filters) == 2
        assert result_filters[0].key == "linked_to"
        assert result_filters[0].value == "Test KB"
        assert result_filters[1].key == "category"
        assert result_filters[1].value == "docs"

    @pytest.mark.asyncio
    async def test_async_search_with_isolation_list_filters_injects_linked_to(self):
        """Test that async search auto-injects linked_to for list-based FilterExpr filters."""
        from agno.filters import EQ

        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Async Test KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        list_filters = [EQ("department", "legal")]

        await knowledge.asearch("test query", filters=list_filters)

        assert len(mock_db.search_calls) == 1
        result_filters = mock_db.search_calls[0]["filters"]
        assert len(result_filters) == 2
        assert result_filters[0].key == "linked_to"
        assert result_filters[0].value == "Async Test KB"
        assert result_filters[1].key == "department"
        assert result_filters[1].value == "legal"

    @pytest.mark.asyncio
    async def test_async_search_with_isolation_injects_filter(self):
        """Test that async search with isolation enabled injects linked_to filter."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Async Test KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        await knowledge.asearch("test query")

        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] == {"linked_to": "Async Test KB"}

    @pytest.mark.asyncio
    async def test_async_search_without_isolation_no_filter(self):
        """Test that async search without isolation does not inject filter."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Async Test KB",
            vector_db=mock_db,
            # isolate_vector_search defaults to False
        )

        await knowledge.asearch("test query")

        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] is None


class TestLinkedToMetadata:
    """Tests for linked_to metadata being added to documents when isolation is enabled."""

    def test_prepare_documents_adds_linked_to_with_isolation(self):
        """Test that linked_to is set to knowledge name when isolation is enabled."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="My Knowledge Base",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert result[0].meta_data["linked_to"] == "My Knowledge Base"

    def test_prepare_documents_adds_linked_to_without_isolation(self):
        """Test that linked_to is always added even when isolate_vector_search is False."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="My Knowledge Base",
            vector_db=mock_db,
            # isolate_vector_search defaults to False
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert result[0].meta_data["linked_to"] == "My Knowledge Base"

    def test_prepare_documents_adds_empty_linked_to_no_name_with_isolation(self):
        """Test that linked_to is set to empty string when knowledge has no name but isolation enabled."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert result[0].meta_data["linked_to"] == ""

    def test_linked_to_always_uses_knowledge_name(self):
        """Test that linked_to always uses the knowledge instance name, overriding any caller-supplied value."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="New KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        # Document already has linked_to in metadata
        documents = [Document(name="doc1", content="content", meta_data={"linked_to": "Old KB"})]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        # The knowledge's name should override since we set it after metadata merge
        assert result[0].meta_data["linked_to"] == "New KB"


class MergingMockVectorDb(MockVectorDb):
    """Mocks how real adapters (LanceDB/PgVector/Qdrant) merge the
    ``filters`` argument over each document's ``meta_data`` at insert time."""

    def insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        for document in documents:
            if filters:
                meta_data = document.meta_data.copy() if document.meta_data else {}
                meta_data.update(filters)
                document.meta_data = meta_data
        self.inserted_documents.extend(documents)

    async def async_insert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.insert(content_hash, documents, filters)


class TestLinkedToOverride:
    """User metadata must not override linked_to isolation."""

    @staticmethod
    def _prepared_documents(knowledge: Knowledge, user_metadata: Dict[str, Any]) -> List[Document]:
        """Merge user metadata, then stamp authoritative linked_to."""
        documents = [Document(name="doc1", content="content")]
        return knowledge._prepare_documents_for_insert(documents, "content-id", metadata=user_metadata)

    def test_user_metadata_cannot_override_linked_to_on_insert(self):
        """An attacker inserting into "tenant-a" with metadata={"linked_to": "tenant-b"}
        must not have their document stored as belonging to tenant-b.
        """
        mock_db = MergingMockVectorDb()
        knowledge = Knowledge(
            name="tenant-a",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        user_metadata = {"linked_to": "tenant-b"}
        documents = self._prepared_documents(knowledge, user_metadata)
        content = Content(name="doc", metadata=user_metadata)
        content.content_hash = "hash"

        knowledge._handle_vector_db_insert(content, documents, upsert=False)

        assert len(mock_db.inserted_documents) == 1
        stored = mock_db.inserted_documents[0]
        assert stored.meta_data["linked_to"] == "tenant-a"

    @pytest.mark.asyncio
    async def test_user_metadata_cannot_override_linked_to_on_ainsert(self):
        """Async variant of the cross-tenant override regression test."""
        mock_db = MergingMockVectorDb()
        knowledge = Knowledge(
            name="tenant-a",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        user_metadata = {"linked_to": "tenant-b"}
        documents = self._prepared_documents(knowledge, user_metadata)
        content = Content(name="doc", metadata=user_metadata)
        content.content_hash = "hash"

        await knowledge._ahandle_vector_db_insert(content, documents, upsert=False)

        assert len(mock_db.inserted_documents) == 1
        stored = mock_db.inserted_documents[0]
        assert stored.meta_data["linked_to"] == "tenant-a"
