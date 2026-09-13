"""Tests for per-user RAG isolation at the Knowledge wrapper layer.

``user_id`` is forwarded straight to ``vector_db.search`` instead of being merged into filters.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from agno.filters import EQ
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge


@pytest.fixture
def fake_vector_db():
    """Records the search/async_search call kwargs; returns no documents."""
    vdb = MagicMock()
    vdb.search.return_value = []

    async def _async_search(**kwargs: Any):
        return []

    vdb.async_search.side_effect = _async_search
    # Real None, so search() skips the SearchType branch instead of an auto-created mock attribute
    vdb.search_type = None
    return vdb


@pytest.fixture
def kb_named(fake_vector_db):
    """Knowledge with a name, so linked_to injection is enabled."""
    return Knowledge(name="docs", isolate_vector_search=True, vector_db=fake_vector_db)


@pytest.fixture
def kb_unnamed(fake_vector_db):
    """Knowledge with no name, so linked_to injection is disabled."""
    return Knowledge(name=None, isolate_vector_search=True, vector_db=fake_vector_db)


class TestSearchForwardsUserId:
    def test_user_id_string_forwarded(self, kb_unnamed, fake_vector_db):
        kb_unnamed.search(query="q", user_id="alice")

        fake_vector_db.search.assert_called_once()
        assert fake_vector_db.search.call_args.kwargs["user_id"] == "alice"

    def test_user_id_none_forwarded(self, kb_unnamed, fake_vector_db):
        kb_unnamed.search(query="q", user_id=None)

        fake_vector_db.search.assert_called_once()
        assert fake_vector_db.search.call_args.kwargs["user_id"] is None

    def test_user_id_default_is_none(self, kb_unnamed, fake_vector_db):
        kb_unnamed.search(query="q")

        assert fake_vector_db.search.call_args.kwargs["user_id"] is None


class TestAsearchForwardsUserId:
    @pytest.mark.asyncio
    async def test_user_id_string_forwarded(self, kb_unnamed, fake_vector_db):
        await kb_unnamed.asearch(query="q", user_id="alice")

        fake_vector_db.async_search.assert_called_once()
        assert fake_vector_db.async_search.call_args.kwargs["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_user_id_none_forwarded(self, kb_unnamed, fake_vector_db):
        await kb_unnamed.asearch(query="q", user_id=None)

        assert fake_vector_db.async_search.call_args.kwargs["user_id"] is None


class TestLinkedToIndependentOfUserId:
    """linked_to goes into filters; user_id rides as its own kwarg."""

    def test_linked_to_injected_when_named_and_isolate_on(self, kb_named, fake_vector_db):
        kb_named.search(query="q", user_id="alice")

        call_kwargs = fake_vector_db.search.call_args.kwargs
        assert call_kwargs["filters"] == {"linked_to": "docs"}
        assert call_kwargs["user_id"] == "alice"
        assert "user_id" not in call_kwargs["filters"]

    def test_linked_to_skipped_when_isolate_off(self, fake_vector_db):
        kb = Knowledge(name="docs", isolate_vector_search=False, vector_db=fake_vector_db)

        kb.search(query="q", user_id="alice")

        call_kwargs = fake_vector_db.search.call_args.kwargs
        assert call_kwargs["filters"] is None
        assert call_kwargs["user_id"] == "alice"

    def test_linked_to_with_user_provided_dict_filters(self, kb_named, fake_vector_db):
        kb_named.search(query="q", filters={"topic": "ml"}, user_id="alice")

        call_kwargs = fake_vector_db.search.call_args.kwargs
        assert call_kwargs["filters"] == {"topic": "ml", "linked_to": "docs"}
        assert call_kwargs["user_id"] == "alice"

    def test_linked_to_with_user_provided_dsl_filters(self, kb_named, fake_vector_db):
        existing = EQ("topic", "ml")

        kb_named.search(query="q", filters=[existing], user_id="alice")

        call_kwargs = fake_vector_db.search.call_args.kwargs
        merged = call_kwargs["filters"]
        assert isinstance(merged, list)
        assert len(merged) == 2
        assert isinstance(merged[0], EQ) and merged[0].key == "linked_to"
        assert merged[1] is existing
        assert call_kwargs["user_id"] == "alice"


class TestUserIdStaysOutOfMetaData:
    def test_user_id_not_written_to_meta_data(self):
        kb = Knowledge(name="docs")
        docs = [Document(name="d", content="c", meta_data={})]

        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")

        assert "user_id" not in prepared[0].meta_data

    def test_existing_meta_data_preserved(self):
        kb = Knowledge(name="docs")
        docs = [Document(name="d", content="c", meta_data={"original": "kept"})]

        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")

        assert prepared[0].meta_data["original"] == "kept"
        assert prepared[0].meta_data["linked_to"] == "docs"
        assert "user_id" not in prepared[0].meta_data

    def test_caller_provided_user_id_in_meta_data_preserved(self):
        kb = Knowledge(name="docs")
        docs = [Document(name="d", content="c", meta_data={"user_id": "this-is-mine-not-yours"})]

        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")

        assert prepared[0].meta_data["user_id"] == "this-is-mine-not-yours"
