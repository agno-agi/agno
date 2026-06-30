"""Tests that the Knowledge wrapper forwards user_id straight to the vector DB.

Each backend isolates natively, so Knowledge.search/asearch pass user_id through
as a kwarg without folding it into the DSL filters or document metadata.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from agno.filters import EQ
from agno.knowledge.document import Document
from agno.knowledge.knowledge import Knowledge


@pytest.fixture
def fake_vector_db():
    """Mock that records search/async_search call kwargs so we can assert on them."""
    vdb = MagicMock()
    vdb.search.return_value = []

    async def _async_search(**kwargs: Any):
        return []

    vdb.async_search.side_effect = _async_search
    # Mark the type so isolate_vector_search dispatch works cleanly
    vdb.search_type = None
    return vdb


@pytest.fixture
def kb_named(fake_vector_db):
    """Knowledge with a name and isolate_vector_search on, so linked_to scope kicks in."""
    return Knowledge(
        name="docs",
        isolate_vector_search=True,
        vector_db=fake_vector_db,
    )


@pytest.fixture
def kb_unnamed(fake_vector_db):
    """Knowledge with no name, so linked_to injection is disabled."""
    return Knowledge(
        name=None,
        isolate_vector_search=True,
        vector_db=fake_vector_db,
    )


class TestSearchForwardsUserId:
    """Knowledge.search(user_id=X) forwards user_id=X to vector_db.search."""

    def test_user_id_string_forwarded(self, kb_unnamed, fake_vector_db):
        kb_unnamed.search(query="q", user_id="alice")
        fake_vector_db.search.assert_called_once()
        call_kwargs = fake_vector_db.search.call_args.kwargs
        assert call_kwargs["user_id"] == "alice"

    def test_user_id_none_forwarded(self, kb_unnamed, fake_vector_db):
        kb_unnamed.search(query="q", user_id=None)
        fake_vector_db.search.assert_called_once()
        call_kwargs = fake_vector_db.search.call_args.kwargs
        # Explicit None means no isolation; backend sees user_id=None
        assert call_kwargs["user_id"] is None

    def test_user_id_default_is_none(self, kb_unnamed, fake_vector_db):
        """Omitting the kwarg defaults to None for backward compatibility."""
        kb_unnamed.search(query="q")
        call_kwargs = fake_vector_db.search.call_args.kwargs
        assert call_kwargs["user_id"] is None


class TestAsearchForwardsUserId:
    """Same contract for the async path."""

    @pytest.mark.asyncio
    async def test_user_id_string_forwarded(self, kb_unnamed, fake_vector_db):
        await kb_unnamed.asearch(query="q", user_id="alice")
        fake_vector_db.async_search.assert_called_once()
        call_kwargs = fake_vector_db.async_search.call_args.kwargs
        assert call_kwargs["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_user_id_none_forwarded(self, kb_unnamed, fake_vector_db):
        await kb_unnamed.asearch(query="q", user_id=None)
        call_kwargs = fake_vector_db.async_search.call_args.kwargs
        assert call_kwargs["user_id"] is None


class TestLinkedToIndependentOfUserId:
    """Instance scope (linked_to) and owner scope (user_id) are orthogonal.

    The first goes into the filters dict; the second rides as a separate kwarg.
    """

    def test_linked_to_injected_when_named_and_isolate_on(self, kb_named, fake_vector_db):
        kb_named.search(query="q", user_id="alice")
        call_kwargs = fake_vector_db.search.call_args.kwargs
        # filters dict gets the instance scope...
        assert call_kwargs["filters"] == {"linked_to": "docs"}
        # ...and user_id rides separately, not inside filters
        assert call_kwargs["user_id"] == "alice"
        assert "user_id" not in call_kwargs["filters"]

    def test_linked_to_skipped_when_isolate_off(self, fake_vector_db):
        kb = Knowledge(name="docs", isolate_vector_search=False, vector_db=fake_vector_db)
        kb.search(query="q", user_id="alice")
        call_kwargs = fake_vector_db.search.call_args.kwargs
        # No filters when isolate_vector_search is off
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
        # linked_to gets prepended as an EQ; original filter preserved
        merged = call_kwargs["filters"]
        assert isinstance(merged, list)
        assert len(merged) == 2
        assert isinstance(merged[0], EQ) and merged[0].key == "linked_to"
        assert merged[1] is existing


class TestPrepareDocumentsForInsertNoUserIdInMetaData:
    """_prepare_documents_for_insert does not stamp user_id into meta_data.

    user_id flows as an explicit parameter on the vector_db.insert /
    async_insert calls instead. linked_to (instance scope) does still go into
    meta_data, since it's a knowledge-instance concern, not per-user.
    """

    def _knowledge(self):
        return Knowledge(name="docs")

    def test_user_id_not_written_to_meta_data(self):
        """user_id stays out of meta_data."""
        kb = self._knowledge()
        docs = [Document(name="d", content="c", meta_data={})]
        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")
        assert "user_id" not in prepared[0].meta_data

    def test_linked_to_still_set(self):
        """Instance scope still flows through meta_data."""
        kb = self._knowledge()
        docs = [Document(name="d", content="c", meta_data={})]
        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")
        assert prepared[0].meta_data["linked_to"] == "docs"

    def test_existing_meta_data_preserved(self):
        """Pre-existing keys on the document's meta_data are not clobbered."""
        kb = self._knowledge()
        docs = [Document(name="d", content="c", meta_data={"original": "kept"})]
        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")
        assert prepared[0].meta_data["original"] == "kept"
        assert prepared[0].meta_data["linked_to"] == "docs"
        assert "user_id" not in prepared[0].meta_data

    def test_caller_provided_user_id_in_meta_data_preserved(self):
        """A user_id key the caller put in their own metadata is left untouched."""
        kb = self._knowledge()
        docs = [Document(name="d", content="c", meta_data={"user_id": "this-is-mine-not-yours"})]
        prepared = kb._prepare_documents_for_insert(docs, content_id="cid")
        # Caller's user_id is left exactly as they set it
        assert prepared[0].meta_data["user_id"] == "this-is-mine-not-yours"
