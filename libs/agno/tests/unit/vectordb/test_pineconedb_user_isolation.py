"""Pinecone per-user RAG isolation contract.

Pinecone stores the owner in the vector's ``metadata`` under a ``user_id``
key. Scoped reads apply an own-OR-shared metadata filter so admin-uploaded
shared content (no ``user_id``) stays discoverable; unscoped (admin) reads
apply no scope. We mock the Pinecone client/index and assert on the filter
sent to ``index.query`` / ``index.delete`` — same approach as the base
``test_pineconedb.py`` suite.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.pineconedb import PineconeDb

TEST_INDEX_NAME = f"isolation_test_{uuid.uuid4().hex[:8]}"
TEST_DIMENSION = 1024
USER_ID_KEY = "user_id"


@pytest.fixture
def mock_pinecone_index():
    """Create a mock Pinecone index."""
    index = MagicMock()
    empty_response = MagicMock()
    empty_response.matches = []
    index.query.return_value = empty_response
    return index


@pytest.fixture
def pinecone_db(mock_pinecone_index, mock_embedder):
    """Create a PineconeDb instance with mocked client and index."""
    with patch("agno.vectordb.pineconedb.pineconedb.Pinecone", return_value=MagicMock()):
        db = PineconeDb(
            name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            spec={"serverless": {"cloud": "aws", "region": "us-west-2"}},
            embedder=mock_embedder,
            api_key="fake-api-key",
        )
        db._client = MagicMock()
        db._index = mock_pinecone_index
        yield db


def _doc(content="hello world", **kwargs):
    return Document(content=content, meta_data={"topic": "t"}, name="d", **kwargs)


def _matches(metadatas):
    """A query response carrying one match per metadata dict, as Pinecone would
    return for a filter those rows satisfy."""
    response = MagicMock()
    response.matches = [MagicMock(id=f"v{i}", metadata=metadata) for i, metadata in enumerate(metadatas)]
    return response


class TestWritePersistsOwner:
    """On write the owner is stamped into ``metadata.user_id``; ``None``
    collapses to the SHARED bucket (no ``user_id`` key)."""

    def test_explicit_user_id_stamped_into_metadata(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)
        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id="alice")

        vectors = pinecone_db.index.upsert.call_args.kwargs["vectors"]
        assert len(vectors) == 1
        assert vectors[0]["metadata"][USER_ID_KEY] == "alice"

    def test_none_user_id_is_shared(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)
        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id=None)

        vectors = pinecone_db.index.upsert.call_args.kwargs["vectors"]
        assert USER_ID_KEY not in vectors[0]["metadata"]

    def test_caller_metadata_cannot_spoof_owner(self, pinecone_db):
        """A caller's own ``user_id`` key in meta_data must not override the owner."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)
        doc = Document(content="c", meta_data={"user_id": "attacker"}, name="d")

        pinecone_db.upsert(content_hash="h1", documents=[doc], user_id="alice")

        vectors = pinecone_db.index.upsert.call_args.kwargs["vectors"]
        assert vectors[0]["metadata"][USER_ID_KEY] == "alice"


class TestSearchIsolationContract:
    """The load-bearing contract: a scoped search filters to the caller's own
    chunks OR the shared bucket, and never another user's. With a mocked index
    the filter sent to ``index.query`` IS the contract."""

    def test_scoped_search_builds_own_or_shared_filter(self, pinecone_db):
        pinecone_db.search(query="q", user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {
            "$or": [
                {USER_ID_KEY: "alice"},
                {USER_ID_KEY: {"$exists": False}},
            ]
        }

    def test_scoped_search_ands_scope_onto_caller_filter(self, pinecone_db):
        caller_filter = {"topic": {"$eq": "t"}}
        pinecone_db.search(query="q", filters=caller_filter, user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {
            "$and": [
                caller_filter,
                {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]},
            ]
        }

    def test_admin_search_has_no_scope(self, pinecone_db):
        """``user_id=None`` means no scope predicate — admin sees everything."""
        pinecone_db.search(query="q", user_id=None)
        assert pinecone_db.index.query.call_args.kwargs["filter"] is None

        pinecone_db.index.query.reset_mock()
        pinecone_db.search(query="q", filters={"topic": {"$eq": "t"}}, user_id=None)
        assert pinecone_db.index.query.call_args.kwargs["filter"] == {"topic": {"$eq": "t"}}

    async def test_async_search_scopes_too(self, pinecone_db):
        await pinecone_db.async_search(query="q", user_id="alice")
        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]}


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the delete
    to the caller's chunks — otherwise Bob could guess Alice's content_id and
    wipe her chunks. Admin (``None``) deletes across all owners."""

    def test_scoped_delete_matches_owner_only(self, pinecone_db):
        pinecone_db.delete_by_content_id("cid-1", user_id="alice")

        # Serverless deletes resolve the scope filter to ids via a query, so the
        # scope is asserted on that query. It matches the owner exactly and does
        # NOT OR in the shared bucket — a scoped caller must not wipe org content.
        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_id": {"$eq": "cid-1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_unscoped_delete_is_content_id_only(self, pinecone_db):
        pinecone_db.delete_by_content_id("cid-1", user_id=None)

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_id": {"$eq": "cid-1"}}


class TestContentHashScoping:
    """The per-user dedup path keys on ``content_hash`` scoped by owner. A
    scoped check/delete touches only that owner's chunks; ``None`` touches
    only the SHARED bucket (owner absent) — never every owner's chunks. The
    check is the guard half of the pair, so it has to mean exactly what the
    delete means, or a shared publish gets skipped on the strength of a
    privately owned row and the shared bucket never receives it."""

    def test_content_hash_exists_scoped_to_owner(self, pinecone_db):
        pinecone_db.content_hash_exists("h1", user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_content_hash_exists_none_is_shared_bucket_only(self, pinecone_db):
        pinecone_db.content_hash_exists("h1", user_id=None)

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}

    def test_content_hash_exists_none_cannot_match_a_privately_owned_row(self, pinecone_db):
        """``$exists: False`` is unsatisfiable for a row carrying an owner, so a
        shared publish is never skipped because some tenant already holds the
        same bytes."""
        sent_filter = None

        def query(**kwargs):
            nonlocal sent_filter
            sent_filter = kwargs["filter"]
            owned = {USER_ID_KEY: "alice", "content_hash": "h1"}
            hit = sent_filter[USER_ID_KEY] == {"$eq": owned[USER_ID_KEY]}
            return _matches([owned] if hit else [])

        pinecone_db.index.query.side_effect = query

        assert pinecone_db.content_hash_exists("h1", user_id=None) is False
        assert pinecone_db.content_hash_exists("h1", user_id="alice") is True

    def test_delete_by_content_hash_scoped_to_owner(self, pinecone_db):
        pinecone_db._delete_by_content_hash("h1", user_id="alice")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_delete_by_content_hash_none_deletes_shared_bucket_only(self, pinecone_db):
        """``None`` must NOT wipe every owner's chunks — only the owner-absent
        shared bucket."""
        pinecone_db._delete_by_content_hash("h1", user_id=None)

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}


class TestStealPrevention:
    """Two owners uploading identical content must both survive. The owner is
    folded into the vector id so ids don't collide, and the upsert dedup
    check/delete is scoped to the writing owner so one can't evict another."""

    def test_owner_folded_id_is_distinct_per_owner(self, pinecone_db):
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="alice")
        alice_id = pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        pinecone_db.index.upsert.reset_mock()
        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="bob")
        bob_id = pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        assert alice_id != bob_id

    def test_shared_upload_keeps_document_id_verbatim(self, pinecone_db):
        """A shared (``user_id=None``) upload is not folded — it round-trips
        on the plain document id."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id=None)
        assert pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"] == "doc-1"

    def test_owner_boundary_cannot_be_shifted(self, pinecone_db):
        """The base id is caller-controlled, so it is collapsed to a fixed-length
        digest before the owner is folded in. Without that, ("doc_1", "alice") and
        ("doc", "1_alice") both join to "doc_1_alice" and land on ONE vector id —
        and every agno chunk id ends in "_<n>", so a caller passing
        user_id="1_alice" overwrites alice's chunk 1."""
        assert pinecone_db._record_id("doc_1", "alice") != pinecone_db._record_id("doc", "1_alice")

    def test_shifted_boundary_write_does_not_overwrite_the_owner(self, pinecone_db):
        """The consequence on the write path: the crafted owner's vector id is not
        alice's, so her vector survives."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc_1")], user_id="alice")
        alice_id = pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc")], user_id="1_alice")
        assert pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"] != alice_id

    async def test_async_upsert_folds_the_same_id(self, pinecone_db):
        """The async write path shares the fold, so the two surfaces agree on the
        key — otherwise a sync re-ingest would not replace an async-written chunk."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="alice")
        sync_id = pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        await pinecone_db.async_upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="alice")
        assert pinecone_db.index.upsert.call_args.kwargs["vectors"][0]["id"] == sync_id

    def test_upsert_dedup_check_is_scoped_to_writing_owner(self, pinecone_db):
        """Bob upserting content Alice already owns must dedup-check only Bob's
        bucket — so Alice's identical chunk is never considered for deletion."""
        pinecone_db.content_hash_exists = MagicMock(return_value=False)

        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id="bob")
        pinecone_db.content_hash_exists.assert_called_once_with("h1", user_id="bob")

    def test_upsert_dedup_delete_is_scoped_to_writing_owner(self, pinecone_db):
        """When the writer's own chunk exists, the pre-delete is scoped to that
        owner, leaving other owners' identical content intact."""
        pinecone_db.content_hash_exists = MagicMock(return_value=True)

        pinecone_db.upsert(content_hash="h1", documents=[_doc()], user_id="bob")

        sent_filter = pinecone_db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "bob"}}
