"""Tests for knowledge instance isolation features.

Tests that knowledge instances with isolate_vector_search=True filter by linked_to.
"""

from typing import Any, Dict, List, Optional

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.knowledge.content import Content, ContentStatus, FileData
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.base import VectorDb


class MockVectorDb(VectorDb):
    """Mock VectorDb that tracks search calls and their filters."""

    def __init__(self):
        self.search_calls: List[Dict[str, Any]] = []
        self.inserted_documents: List[Document] = []
        self.upsert_calls: List[Dict[str, Any]] = []
        self.updated_metadata: List[Dict[str, Any]] = []
        self.deleted_content_ids: List[str] = []

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
        self.upsert_calls.append({"content_hash": content_hash, "documents": documents, "filters": filters})

    async def async_upsert(self, content_hash: str, documents: List[Document], filters=None) -> None:
        self.upsert_calls.append({"content_hash": content_hash, "documents": documents, "filters": filters})

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
        self.updated_metadata.append({"content_id": content_id, "metadata": metadata})

    def delete_by_content_id(self, content_id: str) -> bool:
        self.deleted_content_ids.append(content_id)
        return True

    def get_supported_search_types(self) -> List[str]:
        return ["vector"]


def _upsert_content_row(
    contents_db: InMemoryDb,
    content_id: str,
    linked_to: Optional[str],
    *,
    name: Optional[str] = None,
) -> None:
    contents_db.upsert_knowledge_content(
        KnowledgeRow(
            id=content_id,
            name=name or content_id,
            description="",
            metadata={"seed": content_id},
            linked_to=linked_to,
            status=ContentStatus.COMPLETED,
        )
    )


def _build_isolated_knowledge() -> tuple[Knowledge, InMemoryDb, MockVectorDb]:
    contents_db = InMemoryDb()
    vector_db = MockVectorDb()
    _upsert_content_row(contents_db, "owned", "scope-a")
    _upsert_content_row(contents_db, "foreign", "scope-b")
    _upsert_content_row(contents_db, "legacy", None)
    knowledge = Knowledge(
        name="scope-a",
        contents_db=contents_db,
        vector_db=vector_db,
        isolate_vector_search=True,
    )
    knowledge._enforce_content_isolation = True
    return knowledge, contents_db, vector_db


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


class TestSharedTableIsolationHardening:
    def test_isolated_namespaces_have_distinct_content_and_document_hashes(self):
        vector_db = MockVectorDb()
        scope_a = Knowledge(name="scope-a", vector_db=vector_db, isolate_vector_search=True)
        scope_b = Knowledge(name="scope-b", vector_db=vector_db, isolate_vector_search=True)
        scope_a._enforce_content_isolation = True
        scope_b._enforce_content_isolation = True
        unisolated_a = Knowledge(name="scope-a", vector_db=vector_db)
        unisolated_b = Knowledge(name="scope-b", vector_db=vector_db)
        content = Content(url="https://example.com/docs")
        document = Document(content="same text", meta_data={"url": "https://example.com/docs/page"})

        assert scope_a._build_content_hash(content) != scope_b._build_content_hash(content)
        assert scope_a._build_document_content_hash(document, content) != scope_b._build_document_content_hash(
            document, content
        )
        assert unisolated_a._build_content_hash(content) == unisolated_b._build_content_hash(content)
        assert unisolated_a._build_document_content_hash(
            document, content
        ) == unisolated_b._build_document_content_hash(document, content)

    def test_isolated_vector_metadata_reserves_linked_to(self):
        vector_db = MockVectorDb()
        knowledge = Knowledge(name="scope-a", vector_db=vector_db, isolate_vector_search=True)
        knowledge._enforce_content_isolation = True
        content = Content(
            id="content-id",
            content_hash="content-hash",
            metadata={"category": "docs", "linked_to": "scope-b"},
        )
        documents = [Document(content="content", meta_data={"linked_to": "scope-b"})]

        knowledge._prepare_documents_for_insert(documents, "content-id", metadata=content.metadata)
        knowledge._handle_vector_db_insert(content, documents, upsert=True)

        assert documents[0].meta_data["linked_to"] == "scope-a"
        assert vector_db.upsert_calls[0]["filters"] == {"category": "docs", "linked_to": "scope-a"}

    def test_unisolated_vector_metadata_is_unchanged(self):
        vector_db = MockVectorDb()
        knowledge = Knowledge(name="scope-a", vector_db=vector_db)
        content = Content(
            id="content-id",
            content_hash="content-hash",
            metadata={"category": "docs", "linked_to": "scope-b"},
        )

        knowledge._handle_vector_db_insert(content, [Document(content="content")], upsert=True)

        assert vector_db.upsert_calls[0]["filters"] == {"category": "docs", "linked_to": "scope-b"}

    def test_text_content_size_uses_utf8_bytes(self, monkeypatch):
        knowledge = Knowledge(vector_db=MockVectorDb())
        knowledge._enforce_content_isolation = True
        captured: Dict[str, Content] = {}

        def capture_content(content: Content, *args, **kwargs) -> None:
            captured["content"] = content

        monkeypatch.setattr(knowledge, "_load_content", capture_content)
        knowledge.insert(text_content="café")

        content = captured["content"]
        assert content.file_data == FileData(content="café", type="Text", size=5)
        assert knowledge._build_knowledge_row(content).size == 5

    def test_static_knowledge_preserves_legacy_character_size(self, monkeypatch):
        knowledge = Knowledge(vector_db=MockVectorDb())
        captured: Dict[str, Content] = {}

        def capture_content(content: Content, *args, **kwargs) -> None:
            captured["content"] = content

        monkeypatch.setattr(knowledge, "_load_content", capture_content)
        knowledge.insert(text_content="café")

        content = captured["content"]
        assert content.file_data == FileData(content="café", type="Text")
        assert knowledge._build_knowledge_row(content).size == 4

    def test_sync_content_id_operations_fail_closed_outside_namespace(self):
        knowledge, contents_db, vector_db = _build_isolated_knowledge()

        assert knowledge.get_content_by_id("owned") is not None
        assert knowledge.get_content_by_id("foreign") is None
        assert knowledge.get_content_by_id("legacy") is None
        assert knowledge.get_content_status("owned") == (ContentStatus.COMPLETED, None)
        assert knowledge.get_content_status("foreign") == (None, "Content not found")
        assert knowledge.get_content_status("legacy") == (None, "Content not found")

        assert knowledge.patch_content(Content(id="foreign", name="changed")) is None
        assert knowledge.patch_content(Content(id="legacy", name="changed")) is None
        assert contents_db.get_knowledge_content("foreign").name == "foreign"  # type: ignore[union-attr]
        assert contents_db.get_knowledge_content("legacy").name == "legacy"  # type: ignore[union-attr]
        assert vector_db.updated_metadata == []

        updated = knowledge.patch_content(Content(id="owned", metadata={"category": "updated", "linked_to": "scope-b"}))
        assert updated is not None
        owned_row = contents_db.get_knowledge_content("owned")
        assert owned_row is not None
        assert owned_row.linked_to == "scope-a"
        assert owned_row.metadata == {"seed": "owned", "category": "updated"}
        assert vector_db.updated_metadata == [
            {
                "content_id": "owned",
                "metadata": {"category": "updated", "linked_to": "scope-a"},
            }
        ]

        knowledge.remove_content_by_id("foreign")
        knowledge.remove_content_by_id("legacy")
        assert contents_db.get_knowledge_content("foreign") is not None
        assert contents_db.get_knowledge_content("legacy") is not None
        assert vector_db.deleted_content_ids == []

        knowledge.remove_content_by_id("owned")
        assert contents_db.get_knowledge_content("owned") is None
        assert vector_db.deleted_content_ids == ["owned"]

    @pytest.mark.asyncio
    async def test_async_content_id_operations_fail_closed_outside_namespace(self):
        knowledge, contents_db, vector_db = _build_isolated_knowledge()

        assert await knowledge.aget_content_by_id("foreign") is None
        assert await knowledge.aget_content_by_id("legacy") is None
        assert await knowledge.aget_content_status("foreign") == (None, "Content not found")
        assert await knowledge.aget_content_status("legacy") == (None, "Content not found")
        assert await knowledge.apatch_content(Content(id="foreign", name="changed")) is None
        assert await knowledge.apatch_content(Content(id="legacy", name="changed")) is None

        updated = await knowledge.apatch_content(Content(id="owned", name="updated"))
        assert updated is not None
        assert contents_db.get_knowledge_content("owned").name == "updated"  # type: ignore[union-attr]

        await knowledge.aremove_content_by_id("foreign")
        await knowledge.aremove_content_by_id("legacy")
        assert contents_db.get_knowledge_content("foreign") is not None
        assert contents_db.get_knowledge_content("legacy") is not None
        assert vector_db.deleted_content_ids == []

        await knowledge.aremove_content_by_id("owned")
        assert contents_db.get_knowledge_content("owned") is None
        assert vector_db.deleted_content_ids == ["owned"]

    @pytest.mark.asyncio
    async def test_content_id_operations_preserve_unisolated_behavior(self):
        contents_db = InMemoryDb()
        vector_db = MockVectorDb()
        _upsert_content_row(contents_db, "foreign", "scope-b")
        _upsert_content_row(contents_db, "legacy", None)
        knowledge = Knowledge(name="scope-a", contents_db=contents_db, vector_db=vector_db)

        assert knowledge.get_content_by_id("foreign") is not None
        assert await knowledge.aget_content_by_id("legacy") is not None
        assert knowledge.get_content_status("legacy") == (ContentStatus.COMPLETED, None)
        assert await knowledge.aget_content_status("foreign") == (ContentStatus.COMPLETED, None)
        assert knowledge.patch_content(Content(id="foreign", name="sync-updated")) is not None
        assert await knowledge.apatch_content(Content(id="legacy", name="async-updated")) is not None

        knowledge.remove_content_by_id("foreign")
        await knowledge.aremove_content_by_id("legacy")
        assert contents_db.get_knowledge_content("foreign") is None
        assert contents_db.get_knowledge_content("legacy") is None
        assert vector_db.deleted_content_ids == ["foreign", "legacy"]

    def test_isolated_delete_without_contents_db_fails_closed(self):
        vector_db = MockVectorDb()
        knowledge = Knowledge(name="scope-a", vector_db=vector_db, isolate_vector_search=True)
        knowledge._enforce_content_isolation = True

        knowledge.remove_content_by_id("unknown")

        assert vector_db.deleted_content_ids == []

    def test_existing_vector_isolation_keeps_legacy_content_ids_and_crud_semantics(self):
        contents_db = InMemoryDb()
        vector_db = MockVectorDb()
        _upsert_content_row(contents_db, "foreign", "scope-b")
        scope_a = Knowledge(
            name="scope-a",
            contents_db=contents_db,
            vector_db=vector_db,
            isolate_vector_search=True,
        )
        scope_b = Knowledge(name="scope-b", vector_db=vector_db, isolate_vector_search=True)
        content = Content(url="https://example.com/docs")

        assert scope_a._build_content_hash(content) == scope_b._build_content_hash(content)
        assert scope_a.get_content_by_id("foreign") is not None
