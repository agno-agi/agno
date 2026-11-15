"""Upstash per-user isolation: the owner lives in ``metadata.user_id``, an absent key is the shared bucket."""

from typing import List
from unittest.mock import Mock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.upstashdb.upstashdb import UpstashVectorDb, _always_false


@pytest.fixture
def mock_upstash_index():
    """Fixture to create a mock Upstash index"""
    with patch("upstash_vector.Index") as mock_index_class:
        mock_index = Mock()
        mock_index_class.return_value = mock_index

        mock_info = Mock()
        mock_info.vector_count = 0
        mock_info.dimension = 384
        mock_index.info.return_value = mock_info

        mock_index.upsert.return_value = "Success"
        mock_index.query.return_value = []

        mock_delete_result = Mock()
        mock_delete_result.deleted = 0
        mock_index.delete.return_value = mock_delete_result

        yield mock_index


@pytest.fixture
def upstash_db(mock_upstash_index):
    """Fixture to create an UpstashVectorDb instance using Upstash embeddings"""
    db = UpstashVectorDb(url="https://test-url.upstash.io", token="test-token", embedder=None)
    db._index = mock_upstash_index
    return db


def _docs() -> List[Document]:
    return [
        Document(content="alpha doc", meta_data={"topic": "a"}, name="alpha", id="doc_1", content_id="c1"),
        Document(content="beta doc", meta_data={"topic": "b"}, name="beta", id="doc_2", content_id="c2"),
    ]


class TestWriteStampsOwner:
    """Test owner stamping on write; only ``None`` writes to the shared bucket."""

    def test_explicit_user_id_stamped_into_metadata(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert v.metadata["user_id"] == "alice"

    def test_none_user_id_is_shared(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id=None)
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert "user_id" not in v.metadata

    def test_empty_string_user_id_is_a_real_tenant(self, upstash_db):
        """``""`` is a real tenant stamped verbatim; only ``None`` omits the owner key."""
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert v.metadata["user_id"] == ""

    def test_caller_filter_cannot_override_owner(self, upstash_db):
        """A caller passing their own user_id in filters must not reassign tenancy."""
        upstash_db.upsert(content_hash="h1", documents=_docs(), filters={"user_id": "bob"}, user_id="alice")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert v.metadata["user_id"] == "alice"


class TestSearchScope:
    """Test that a scoped search matches the caller's own chunks or the shared bucket."""

    def test_scoped_search_builds_own_or_shared_filter(self, upstash_db):
        upstash_db.search("q", user_id="alice")
        sent_filter = upstash_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == '(user_id = "alice" OR HAS NOT FIELD user_id)'
        assert "bob" not in sent_filter

    def test_admin_search_has_no_scope(self, upstash_db):
        upstash_db.search("q", user_id=None)
        assert upstash_db.index.query.call_args.kwargs["filter"] == ""


class TestDeleteScope:
    """Test that ``delete_by_content_id`` scopes the delete to the caller's chunks."""

    def test_scoped_delete_matches_owner_only(self, upstash_db):
        upstash_db.delete_by_content_id("c1", user_id="alice")
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_id = "c1" AND user_id = "alice"'

    def test_unscoped_delete_is_content_id_only(self, upstash_db):
        upstash_db.delete_by_content_id("c1", user_id=None)
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_id = "c1"'


class TestOwnerFoldedId:
    """Test that the owner is folded into the vector id so two owners' identical content cannot collide."""

    def test_two_owners_same_content_get_distinct_ids(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
        alice_ids = {v.id for v in upstash_db.index.upsert.call_args[0][0]}
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="bob")
        bob_ids = {v.id for v in upstash_db.index.upsert.call_args[0][0]}
        assert alice_ids.isdisjoint(bob_ids)

    def test_shared_bucket_keeps_base_id(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id=None)
        ids = [v.id for v in upstash_db.index.upsert.call_args[0][0]]
        assert ids == ["doc_1", "doc_2"]


class TestIdLessDocument:
    """A Document carries no id unless the caller set one, so the adapter has to supply one.

    Dropping it loses the chunk silently, and folding an owner into ``None`` raises.
    """

    def _idless(self) -> List[Document]:
        return [Document(content="alpha doc", name="alpha", content_id="c1")]

    @pytest.mark.parametrize("user_id", [None, "alice"])
    def test_an_id_less_document_is_ingested(self, upstash_db, user_id):
        upstash_db.upsert(content_hash="h1", documents=self._idless(), user_id=user_id)

        vectors = upstash_db.index.upsert.call_args[0][0]
        assert len(vectors) == 1
        assert vectors[0].id

    def test_the_generated_id_is_stable_for_the_same_content(self, upstash_db, mock_upstash_index):
        upstash_db.upsert(content_hash="h1", documents=self._idless(), user_id="alice")
        first = upstash_db.index.upsert.call_args[0][0][0].id

        upstash_db.upsert(content_hash="h1", documents=self._idless(), user_id="alice")
        second = upstash_db.index.upsert.call_args[0][0][0].id

        assert first == second

    def test_two_owners_of_id_less_content_stay_distinct(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=self._idless(), user_id="alice")
        alice = upstash_db.index.upsert.call_args[0][0][0].id

        upstash_db.upsert(content_hash="h1", documents=self._idless(), user_id="bob")
        bob = upstash_db.index.upsert.call_args[0][0][0].id

        assert alice != bob


class TestFilterInjectionBlocked:
    """A crafted user_id must never break out of its filter literal to leak another owner's chunks."""

    def test_double_quote_user_id_cannot_break_out(self, upstash_db):
        # A double-quoted id is wrapped in single quotes, so the OR stays inside the literal.
        malicious = 'alice" OR user_id != "zzz'
        upstash_db.search("q", user_id=malicious)
        sent = upstash_db.index.query.call_args.kwargs["filter"]
        assert sent == "(user_id = 'alice\" OR user_id != \"zzz' OR HAS NOT FIELD user_id)"

    def test_always_false_predicate_is_unsatisfiable(self):
        # Spelled out, not built from the helper: an expected value that calls it would move with a bad mutation.
        assert _always_false("user_id") == "(HAS FIELD user_id AND HAS NOT FIELD user_id)"

    def test_both_quotes_user_id_fails_closed_on_search(self, upstash_db):
        # No literal form => own-scope collapses to always-false, so the caller sees only the shared bucket.
        upstash_db.search("q", user_id="a\"b'c")
        sent = upstash_db.index.query.call_args.kwargs["filter"]
        assert sent == "((HAS FIELD user_id AND HAS NOT FIELD user_id) OR HAS NOT FIELD user_id)"

    def test_both_quotes_user_id_rejected_on_write(self, upstash_db):
        # Fail loud at write time: an unstampable owner would be owner-invisible.
        with pytest.raises(ValueError):
            upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="a\"b'c")


class TestDedupScope:
    """Test that a shared (``user_id=None``) re-ingest scopes its dedup delete to the shared bucket."""

    def test_none_delete_scopes_to_shared_bucket(self, upstash_db):
        upstash_db._delete_by_content_hash("h1", user_id=None)
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_hash = "h1" AND HAS NOT FIELD user_id'

    def test_scoped_delete_scopes_to_owner(self, upstash_db):
        upstash_db._delete_by_content_hash("h1", user_id="alice")
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_hash = "h1" AND user_id = "alice"'

    def test_shared_reingest_only_deletes_shared_rows(self, upstash_db):
        # content_hash already present => upsert runs a scoped dedup delete first.
        upstash_db.index.query.return_value = [Mock()]
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id=None)
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_hash = "h1" AND HAS NOT FIELD user_id'


class TestAsyncIsolation:
    """Test the async write path; ``async_search`` raises NotImplementedError on Upstash."""

    @pytest.mark.asyncio
    async def test_async_write_persists_owner(self, upstash_db):
        await upstash_db.async_upsert(content_hash="h1", documents=_docs(), user_id="alice")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert v.metadata["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_async_write_none_is_shared(self, upstash_db):
        await upstash_db.async_upsert(content_hash="h1", documents=_docs(), user_id=None)
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert "user_id" not in v.metadata
