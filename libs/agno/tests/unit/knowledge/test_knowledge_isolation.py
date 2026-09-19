"""Tests that knowledge instances with isolate_vector_search=True filter by linked_to."""

import pytest

from agno.filters import EQ
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge


class TestKnowledgeIsolation:
    """Tests for knowledge isolation based on isolate_vector_search flag."""

    def test_search_with_isolation_enabled_injects_filter(self, vector_db):
        """Test that search with isolate_vector_search=True injects linked_to filter."""
        knowledge = Knowledge(
            name="Test KB",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        knowledge.search("test query")

        assert len(vector_db.search_calls) == 1
        assert vector_db.search_calls[0]["filters"] == {"linked_to": "Test KB"}

    def test_search_without_isolation_no_filter(self, vector_db):
        """Test that search without isolate_vector_search does not inject filter (backwards compatible)."""
        knowledge = Knowledge(
            name="Test KB",
            vector_db=vector_db,
            # isolate_vector_search defaults to False
        )

        knowledge.search("test query")

        assert len(vector_db.search_calls) == 1
        assert vector_db.search_calls[0]["filters"] is None

    def test_search_without_name_no_filter(self, vector_db):
        """Test that search without name does not inject filter even with isolation enabled."""
        knowledge = Knowledge(
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        knowledge.search("test query")

        assert len(vector_db.search_calls) == 1
        assert vector_db.search_calls[0]["filters"] is None

    def test_search_with_isolation_merges_existing_dict_filters(self, vector_db):
        """Test that linked_to filter merges with existing dict filters when isolation enabled."""
        knowledge = Knowledge(
            name="Test KB",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        knowledge.search("test query", filters={"category": "docs"})

        assert len(vector_db.search_calls) == 1
        assert vector_db.search_calls[0]["filters"] == {"category": "docs", "linked_to": "Test KB"}

    def test_search_with_isolation_list_filters_injects_linked_to(self, vector_db):
        """Test that linked_to filter is auto-injected for list-based FilterExpr filters."""
        knowledge = Knowledge(
            name="Test KB",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        list_filters = [EQ("category", "docs")]

        knowledge.search("test query", filters=list_filters)

        assert len(vector_db.search_calls) == 1
        result_filters = vector_db.search_calls[0]["filters"]
        assert len(result_filters) == 2
        assert result_filters[0].key == "linked_to"
        assert result_filters[0].value == "Test KB"
        assert result_filters[1].key == "category"
        assert result_filters[1].value == "docs"

    @pytest.mark.asyncio
    async def test_async_search_with_isolation_list_filters_injects_linked_to(self, vector_db):
        """Test that async search auto-injects linked_to for list-based FilterExpr filters."""
        knowledge = Knowledge(
            name="Async Test KB",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        list_filters = [EQ("department", "legal")]

        await knowledge.asearch("test query", filters=list_filters)

        assert len(vector_db.search_calls) == 1
        result_filters = vector_db.search_calls[0]["filters"]
        assert len(result_filters) == 2
        assert result_filters[0].key == "linked_to"
        assert result_filters[0].value == "Async Test KB"
        assert result_filters[1].key == "department"
        assert result_filters[1].value == "legal"

    @pytest.mark.asyncio
    async def test_async_search_with_isolation_injects_filter(self, vector_db):
        """Test that async search with isolation enabled injects linked_to filter."""
        knowledge = Knowledge(
            name="Async Test KB",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        await knowledge.asearch("test query")

        assert len(vector_db.search_calls) == 1
        assert vector_db.search_calls[0]["filters"] == {"linked_to": "Async Test KB"}

    @pytest.mark.asyncio
    async def test_async_search_without_isolation_no_filter(self, vector_db):
        """Test that async search without isolation does not inject filter."""
        knowledge = Knowledge(
            name="Async Test KB",
            vector_db=vector_db,
            # isolate_vector_search defaults to False
        )

        await knowledge.asearch("test query")

        assert len(vector_db.search_calls) == 1
        assert vector_db.search_calls[0]["filters"] is None


class TestLinkedToMetadata:
    """Tests for linked_to metadata being added to documents when isolation is enabled."""

    def test_prepare_documents_adds_linked_to_with_isolation(self, vector_db):
        """Test that linked_to is set to knowledge name when isolation is enabled."""
        knowledge = Knowledge(
            name="My Knowledge Base",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert result[0].meta_data["linked_to"] == "My Knowledge Base"

    def test_prepare_documents_adds_linked_to_without_isolation(self, vector_db):
        """Test that linked_to is always added even when isolate_vector_search is False."""
        knowledge = Knowledge(
            name="My Knowledge Base",
            vector_db=vector_db,
            # isolate_vector_search defaults to False
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert result[0].meta_data["linked_to"] == "My Knowledge Base"

    def test_prepare_documents_adds_empty_linked_to_no_name_with_isolation(self, vector_db):
        """Test that linked_to is set to empty string when knowledge has no name but isolation enabled."""
        knowledge = Knowledge(
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        documents = [Document(name="doc1", content="content")]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        assert result[0].meta_data["linked_to"] == ""

    def test_linked_to_always_uses_knowledge_name(self, vector_db):
        """Test that linked_to always uses the knowledge instance name, overriding any caller-supplied value."""
        knowledge = Knowledge(
            name="New KB",
            vector_db=vector_db,
            isolate_vector_search=True,
        )

        # Document already has linked_to in metadata
        documents = [Document(name="doc1", content="content", meta_data={"linked_to": "Old KB"})]
        result = knowledge._prepare_documents_for_insert(documents, "content-id")

        # The knowledge's name should override since we set it after metadata merge
        assert result[0].meta_data["linked_to"] == "New KB"
