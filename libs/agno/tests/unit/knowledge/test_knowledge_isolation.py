"""Tests for knowledge instance isolation features.

Tests that knowledge instances with isolate_vector_search=True filter by linked_to.
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from agno.db.schemas.knowledge import KnowledgeRow
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

    def test_search_with_isolation_list_filters_gets_linked_to(self):
        """Test that list filters also get linked_to injected automatically."""
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
        assert result_filters[0].key == "category" and result_filters[0].value == "docs"
        assert result_filters[1].key == "linked_to" and result_filters[1].value == "Test KB"

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


class TestContentByIdIsolation:
    """Tests for IDOR protection in content-by-ID methods."""

    def _make_mock_db(self, linked_to: str = "KB-A"):
        mock_db = MagicMock()
        mock_db.get_knowledge_content.return_value = KnowledgeRow(
            name="test-content",
            description="desc",
            linked_to=linked_to,
            status="completed",
            status_message="ok",
        )
        return mock_db

    def test_get_content_by_id_blocks_cross_instance(self):
        mock_contents_db = self._make_mock_db(linked_to="KB-A")
        knowledge = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            contents_db=mock_contents_db,
            isolate_vector_search=True,
        )
        result = knowledge.get_content_by_id("some-id")
        assert result is None

    def test_get_content_by_id_allows_same_instance(self):
        mock_contents_db = self._make_mock_db(linked_to="KB-A")
        knowledge = Knowledge(
            name="KB-A",
            vector_db=MockVectorDb(),
            contents_db=mock_contents_db,
            isolate_vector_search=True,
        )
        result = knowledge.get_content_by_id("some-id")
        assert result is not None

    def test_get_content_by_id_no_isolation_allows_cross_instance(self):
        mock_contents_db = self._make_mock_db(linked_to="KB-A")
        knowledge = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            contents_db=mock_contents_db,
            isolate_vector_search=False,
        )
        result = knowledge.get_content_by_id("some-id")
        assert result is not None

    def test_get_content_status_blocks_cross_instance(self):
        mock_contents_db = self._make_mock_db(linked_to="KB-A")
        knowledge = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            contents_db=mock_contents_db,
            isolate_vector_search=True,
        )
        status, msg = knowledge.get_content_status("some-id")
        assert status is None
        assert msg == "Content not found"

    @pytest.mark.asyncio
    async def test_aget_content_by_id_blocks_cross_instance(self):
        mock_contents_db = self._make_mock_db(linked_to="KB-A")
        knowledge = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            contents_db=mock_contents_db,
            isolate_vector_search=True,
        )
        result = await knowledge.aget_content_by_id("some-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_aget_content_status_blocks_cross_instance(self):
        mock_contents_db = self._make_mock_db(linked_to="KB-A")
        knowledge = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            contents_db=mock_contents_db,
            isolate_vector_search=True,
        )
        status, msg = await knowledge.aget_content_status("some-id")
        assert status is None
        assert msg == "Content not found"


class TestContentHashIsolation:
    """Tests that knowledge name is included in content hash when isolation is enabled."""

    def test_hash_includes_name_with_isolation(self):
        knowledge = Knowledge(
            name="KB-A",
            vector_db=MockVectorDb(),
            isolate_vector_search=True,
        )
        content = Content(name="doc", url="https://example.com")
        hash_a = knowledge._build_content_hash(content)

        knowledge_b = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            isolate_vector_search=True,
        )
        hash_b = knowledge_b._build_content_hash(content)

        assert hash_a != hash_b

    def test_hash_same_without_isolation(self):
        knowledge_a = Knowledge(
            name="KB-A",
            vector_db=MockVectorDb(),
            isolate_vector_search=False,
        )
        knowledge_b = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            isolate_vector_search=False,
        )
        content = Content(name="doc", url="https://example.com")
        assert knowledge_a._build_content_hash(content) == knowledge_b._build_content_hash(content)

    def test_document_hash_includes_name_with_isolation(self):
        knowledge_a = Knowledge(
            name="KB-A",
            vector_db=MockVectorDb(),
            isolate_vector_search=True,
        )
        knowledge_b = Knowledge(
            name="KB-B",
            vector_db=MockVectorDb(),
            isolate_vector_search=True,
        )
        content = Content(name="doc", url="https://example.com")
        document = Document(name="page", content="content", meta_data={"url": "https://example.com/page"})
        hash_a = knowledge_a._build_document_content_hash(document, content)
        hash_b = knowledge_b._build_document_content_hash(document, content)
        assert hash_a != hash_b


class TestAsyncSearchFallback:
    """Tests that async search sync fallback uses asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_async_fallback_uses_to_thread(self):
        mock_db = MockVectorDb()

        async def raise_not_implemented(*args, **kwargs):
            raise NotImplementedError

        mock_db.async_search = raise_not_implemented

        knowledge = Knowledge(
            name="Test KB",
            vector_db=mock_db,
        )

        results = await knowledge.asearch("test query")
        assert len(mock_db.search_calls) == 1
        assert results[0].name == "test"
