"""Tests for knowledge instance isolation features.

Tests that knowledge instances with isolate_vector_search=True filter by linked_to.
"""

from typing import Any, Dict, List

import pytest

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

    def test_search_with_isolation_list_filters_passed_through(self):
        """Test that list filters are passed through without modification."""
        from agno.filters import EQ

        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="Test KB",
            vector_db=mock_db,
            isolate_vector_search=True,
        )

        # Use list-based filters (user must add linked_to manually)
        list_filters = [EQ("category", "docs")]

        knowledge.search("test query", filters=list_filters)

        # List filters passed through unchanged (user responsibility to add linked_to)
        assert len(mock_db.search_calls) == 1
        assert mock_db.search_calls[0]["filters"] == list_filters

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

    def test_prepare_documents_adds_empty_linked_to_without_name(self):
        """Test that linked_to is set to empty string when knowledge has no name."""
        mock_db = MockVectorDb()
        knowledge = Knowledge(
            name="My Knowledge Base",
            vector_db=mock_db,
            # isolate_vector_search defaults to False
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert "linked_to" not in result[0].meta_data

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
