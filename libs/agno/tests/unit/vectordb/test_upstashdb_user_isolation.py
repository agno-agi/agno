"""Upstash per-user RAG isolation contract.

Upstash stores the owner in the vector's ``metadata`` under a ``user_id``
key. Scoped reads apply an own-OR-shared filter string so admin-uploaded
shared content (no ``user_id`` field) stays discoverable; unscoped (admin)
reads apply no scope. We mock the Upstash Index and assert on the filter
sent to ``index.query`` / ``index.delete`` — same approach as the base
``test_upstashdb.py`` suite (no live REST endpoint).
"""

from typing import List
from unittest.mock import Mock, patch

import pytest

# Skip the whole module cleanly if the optional dep is absent.
pytest.importorskip("upstash_vector")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.upstashdb.upstashdb import _ALWAYS_FALSE, UpstashVectorDb  # noqa: E402


@pytest.fixture
def mock_upstash_index():
    """A mocked Upstash Index so no live REST endpoint is needed."""
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
    """An UpstashVectorDb using Upstash hosted embeddings (no embedder)."""
    db = UpstashVectorDb(url="https://test-url.upstash.io", token="test-token", embedder=None)
    db._index = mock_upstash_index
    return db


def _docs() -> List[Document]:
    return [
        Document(content="alpha doc", meta_data={"topic": "a"}, name="alpha", id="doc_1", content_id="c1"),
        Document(content="beta doc", meta_data={"topic": "b"}, name="beta", id="doc_2", content_id="c2"),
    ]


class TestWritePersistsOwner:
    """On write the owner is stamped into ``metadata.user_id``; ``None``/``""``
    collapse to the SHARED bucket (no ``user_id`` key)."""

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

    def test_empty_string_user_id_is_shared(self, upstash_db):
        """normalize_user_id collapses "" to None => shared bucket."""
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert "user_id" not in v.metadata

    def test_caller_filter_cannot_override_owner(self, upstash_db):
        """A caller passing their own user_id in filters must not reassign tenancy."""
        upstash_db.upsert(content_hash="h1", documents=_docs(), filters={"user_id": "bob"}, user_id="alice")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert v.metadata["user_id"] == "alice"


class TestSearchIsolationContract:
    """The load-bearing contract: a scoped search filters to the caller's own
    chunks OR the shared bucket, and never another user's. With a mocked index
    the filter sent to ``index.query`` IS the contract — an own-OR-shared
    predicate excludes bob by construction, while admin (``None``) has no scope.
    """

    def test_scoped_search_builds_own_or_shared_filter(self, upstash_db):
        upstash_db.search("q", user_id="alice")
        sent_filter = upstash_db.index.query.call_args.kwargs["filter"]
        # Own-OR-shared predicate: matches alice's chunks OR the shared bucket,
        # and by construction never another owner's.
        assert sent_filter == '(user_id = "alice" OR HAS NOT FIELD user_id)'
        assert "bob" not in sent_filter

    def test_admin_search_has_no_scope(self, upstash_db):
        """user_id=None => no scope predicate; admin sees everything."""
        upstash_db.search("q", user_id=None)
        assert upstash_db.index.query.call_args.kwargs["filter"] == ""


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the delete
    to the caller's chunks — otherwise Bob could guess Alice's content_id and
    wipe her chunks. Admin (``None``) deletes across all owners."""

    def test_scoped_delete_matches_owner_only(self, upstash_db):
        upstash_db.delete_by_content_id("c1", user_id="alice")
        # Scoped delete ANDs the owner onto the content_id, so Bob cannot wipe
        # Alice's chunks by guessing her content_id.
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_id = "c1" AND user_id = "alice"'

    def test_unscoped_delete_is_content_id_only(self, upstash_db):
        upstash_db.delete_by_content_id("c1", user_id=None)
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_id = "c1"'


class TestStealPreventionOwnerFoldedId:
    """Two owners uploading identical content must not collide: the owner is
    folded into the vector id, so one owner's write can never overwrite (steal)
    the other's identical-content row. The shared bucket keeps the base id."""

    def test_two_owners_same_content_get_distinct_ids(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="alice")
        alice_ids = {v.id for v in upstash_db.index.upsert.call_args[0][0]}
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="bob")
        bob_ids = {v.id for v in upstash_db.index.upsert.call_args[0][0]}
        # Distinct id spaces => bob's upsert cannot overwrite alice's rows.
        assert alice_ids.isdisjoint(bob_ids)

    def test_shared_bucket_keeps_base_id(self, upstash_db):
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id=None)
        ids = [v.id for v in upstash_db.index.upsert.call_args[0][0]]
        assert ids == ["doc_1", "doc_2"]


class TestFilterInjectionBlocked:
    """A crafted user_id must never break out of its filter literal to leak
    another owner's chunks. Values are quoted (Upstash processes no escapes);
    a value carrying both quote chars is unrepresentable and fails CLOSED."""

    def test_double_quote_user_id_cannot_break_out(self, upstash_db):
        # A double-quote-laden id is wrapped in single quotes, so the embedded
        # OR clause stays inside the literal instead of widening the scope.
        malicious = 'alice" OR user_id != "zzz'
        upstash_db.search("q", user_id=malicious)
        sent = upstash_db.index.query.call_args.kwargs["filter"]
        assert sent == "(user_id = 'alice\" OR user_id != \"zzz' OR HAS NOT FIELD user_id)"

    def test_both_quotes_user_id_fails_closed_on_search(self, upstash_db):
        # No literal form => own-scope collapses to an always-false predicate,
        # so such a caller sees only the shared bucket, never anyone's chunks.
        upstash_db.search("q", user_id="a\"b'c")
        sent = upstash_db.index.query.call_args.kwargs["filter"]
        assert sent == f"({_ALWAYS_FALSE} OR HAS NOT FIELD user_id)"

    def test_both_quotes_user_id_rejected_on_write(self, upstash_db):
        # Fail loud at write time: an unstampable owner would be owner-invisible.
        with pytest.raises(ValueError):
            upstash_db.upsert(content_hash="h1", documents=_docs(), user_id="a\"b'c")


class TestSharedBucketDedup:
    """None-dedup: a shared (user_id=None) delete/re-ingest must scope to the
    shared bucket (HAS NOT FIELD user_id), never wipe every owner's chunks."""

    def test_none_delete_scopes_to_shared_bucket(self, upstash_db):
        upstash_db._delete_by_content_hash("h1", user_id=None)
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_hash = "h1" AND HAS NOT FIELD user_id'

    def test_scoped_delete_scopes_to_owner(self, upstash_db):
        upstash_db._delete_by_content_hash("h1", user_id="alice")
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_hash = "h1" AND user_id = "alice"'

    def test_shared_reingest_only_deletes_shared_rows(self, upstash_db):
        # content_hash already present => upsert runs a scoped dedup delete first.
        # It must target only the shared bucket, leaving an owned identical row alive.
        upstash_db.index.query.return_value = [Mock()]
        upstash_db.upsert(content_hash="h1", documents=_docs(), user_id=None)
        assert upstash_db.index.delete.call_args.kwargs["filter"] == 'content_hash = "h1" AND HAS NOT FIELD user_id'


class TestAsyncCoverage:
    """Upstash's ``async_search`` raises NotImplementedError by design, so the
    async write path (``async_upsert``, aliased by ``async_insert``) is the
    async coverage — it must stamp the owner exactly like the sync path."""

    async def test_async_write_persists_owner(self, upstash_db):
        await upstash_db.async_upsert(content_hash="h1", documents=_docs(), user_id="alice")
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert v.metadata["user_id"] == "alice"

    async def test_async_write_none_is_shared(self, upstash_db):
        await upstash_db.async_upsert(content_hash="h1", documents=_docs(), user_id=None)
        vectors = upstash_db.index.upsert.call_args[0][0]
        for v in vectors:
            assert "user_id" not in v.metadata

    async def test_async_search_not_supported(self, upstash_db):
        with pytest.raises(NotImplementedError):
            await upstash_db.async_search("q", user_id="alice")
