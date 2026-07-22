"""Pinecone per-user RAG isolation contract.

Pinecone stores the owner in the vector's ``metadata`` under a ``user_id``
key. Scoped reads apply an own-OR-shared metadata filter so admin-uploaded
shared content (no ``user_id``) stays discoverable; unscoped (admin) reads
apply no scope. We mock the Pinecone client/index and assert on the filter
sent to ``index.query`` / ``index.delete`` — same approach as the base
``test_pineconedb.py`` suite (no network, no real API key).
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

# Skip cleanly if the optional dependency isn't installed.
pytest.importorskip("pinecone")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.pineconedb import PineconeDb  # noqa: E402

TEST_INDEX_NAME = f"isolation_test_{uuid.uuid4().hex[:8]}"
TEST_DIMENSION = 8
USER_ID_KEY = "user_id"


@pytest.fixture
def mock_embedder():
    """A tiny sync embedder that needs no network or API key."""
    mock = MagicMock()
    mock.dimensions = TEST_DIMENSION
    mock.enable_batch = False
    vector = [0.1] * TEST_DIMENSION
    mock.get_embedding.return_value = vector
    mock.get_embedding_and_usage.return_value = (vector, {"total_tokens": 1})
    return mock


@pytest.fixture
def db(mock_embedder):
    """A PineconeDb with the client and index mocked out."""
    index = MagicMock()
    empty_response = MagicMock()
    empty_response.matches = []
    index.query.return_value = empty_response

    with patch("agno.vectordb.pineconedb.pineconedb.Pinecone", return_value=MagicMock()):
        vector_db = PineconeDb(
            name=TEST_INDEX_NAME,
            dimension=TEST_DIMENSION,
            spec={"serverless": {"cloud": "aws", "region": "us-west-2"}},
            embedder=mock_embedder,
            api_key="fake-api-key",
        )
        vector_db._client = MagicMock()
        vector_db._index = index
        yield vector_db


def _doc(content="hello world", **kwargs):
    return Document(content=content, meta_data={"topic": "t"}, name="d", **kwargs)


class TestWritePersistsOwner:
    """On write the owner is stamped into ``metadata.user_id``; ``None``/``""``
    collapse to the SHARED bucket (no ``user_id`` key)."""

    def test_explicit_user_id_stamped_into_metadata(self, db):
        db.content_hash_exists = MagicMock(return_value=False)
        db.upsert(content_hash="h1", documents=[_doc()], user_id="alice")

        vectors = db.index.upsert.call_args.kwargs["vectors"]
        assert len(vectors) == 1
        assert vectors[0]["metadata"][USER_ID_KEY] == "alice"

    def test_none_user_id_is_shared(self, db):
        db.content_hash_exists = MagicMock(return_value=False)
        db.upsert(content_hash="h1", documents=[_doc()], user_id=None)

        vectors = db.index.upsert.call_args.kwargs["vectors"]
        assert USER_ID_KEY not in vectors[0]["metadata"]

    def test_caller_metadata_cannot_spoof_owner(self, db):
        """A caller's own ``user_id`` key in meta_data must not override the owner."""
        db.content_hash_exists = MagicMock(return_value=False)
        doc = Document(content="c", meta_data={"user_id": "attacker"}, name="d")

        db.upsert(content_hash="h1", documents=[doc], user_id="alice")

        vectors = db.index.upsert.call_args.kwargs["vectors"]
        assert vectors[0]["metadata"][USER_ID_KEY] == "alice"


class TestSearchIsolationContract:
    """The load-bearing contract: a scoped search filters to the caller's own
    chunks OR the shared bucket, and never another user's. With a mocked index
    the filter sent to ``index.query`` IS the contract — an own-OR-shared
    predicate excludes bob by construction, while admin (``None``) has no scope.
    """

    def test_scoped_search_builds_own_or_shared_filter(self, db):
        db.search(query="q", user_id="alice")

        sent_filter = db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {
            "$or": [
                {USER_ID_KEY: "alice"},
                {USER_ID_KEY: {"$exists": False}},
            ]
        }

    def test_scoped_search_ands_scope_onto_caller_filter(self, db):
        caller_filter = {"topic": {"$eq": "t"}}
        db.search(query="q", filters=caller_filter, user_id="alice")

        sent_filter = db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {
            "$and": [
                caller_filter,
                {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]},
            ]
        }

    def test_admin_search_has_no_scope(self, db):
        """user_id=None -> no scope predicate; admin sees everything."""
        db.search(query="q", user_id=None)
        assert db.index.query.call_args.kwargs["filter"] is None

        db.index.query.reset_mock()
        db.search(query="q", filters={"topic": {"$eq": "t"}}, user_id=None)
        assert db.index.query.call_args.kwargs["filter"] == {"topic": {"$eq": "t"}}

    async def test_async_search_scopes_too(self, db):
        await db.async_search(query="q", user_id="alice")
        sent_filter = db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]}


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope the delete
    to the caller's chunks — otherwise Bob could guess Alice's content_id and
    wipe her chunks. Admin (``None``) deletes across all owners."""

    def test_scoped_delete_matches_owner_only(self, db):
        db.delete_by_content_id("cid-1", user_id="alice")

        sent_filter = db.index.delete.call_args.kwargs["filter"]
        # Scoped delete matches the owner EXACTLY and does NOT OR in the shared
        # bucket — a scoped caller must not be able to wipe org content.
        assert sent_filter == {"content_id": {"$eq": "cid-1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_unscoped_delete_is_content_id_only(self, db):
        db.delete_by_content_id("cid-1", user_id=None)

        sent_filter = db.index.delete.call_args.kwargs["filter"]
        assert sent_filter == {"content_id": {"$eq": "cid-1"}}


class TestContentHashScoping:
    """The per-user dedup path keys on ``content_hash`` scoped by owner. A
    scoped check/delete touches only that owner's chunks; ``None`` touches
    only the SHARED bucket (owner absent) — never every owner's chunks."""

    def test_content_hash_exists_scoped_to_owner(self, db):
        db.content_hash_exists("h1", user_id="alice")

        sent_filter = db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_content_hash_exists_none_is_shared_bucket_only(self, db):
        db.content_hash_exists("h1", user_id=None)

        sent_filter = db.index.query.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}

    def test_delete_by_content_hash_scoped_to_owner(self, db):
        db._delete_by_content_hash("h1", user_id="alice")

        sent_filter = db.index.delete.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}

    def test_delete_by_content_hash_none_deletes_shared_bucket_only(self, db):
        """``None`` must NOT wipe every owner's chunks — only the owner-absent
        shared bucket, matching the base per-user contract."""
        db._delete_by_content_hash("h1", user_id=None)

        sent_filter = db.index.delete.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}


class TestStealPrevention:
    """Two owners uploading identical content must both survive. The owner is
    folded into the vector id so ids don't collide, and the upsert dedup
    check/delete is scoped to the writing owner so one can't evict another."""

    def test_owner_folded_id_is_distinct_per_owner(self, db):
        db.content_hash_exists = MagicMock(return_value=False)

        db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="alice")
        alice_id = db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        db.index.upsert.reset_mock()
        db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id="bob")
        bob_id = db.index.upsert.call_args.kwargs["vectors"][0]["id"]

        assert alice_id != bob_id

    def test_shared_upload_keeps_document_id_verbatim(self, db):
        """A shared (``user_id=None``) upload is not folded, so it round-trips
        on the plain document id."""
        db.content_hash_exists = MagicMock(return_value=False)

        db.upsert(content_hash="h1", documents=[_doc(content="same", id="doc-1")], user_id=None)
        assert db.index.upsert.call_args.kwargs["vectors"][0]["id"] == "doc-1"

    def test_upsert_dedup_check_is_scoped_to_writing_owner(self, db):
        """Bob upserting content Alice already owns must dedup-check only Bob's
        bucket — so Alice's identical chunk is never considered for deletion."""
        db.content_hash_exists = MagicMock(return_value=False)

        db.upsert(content_hash="h1", documents=[_doc()], user_id="bob")
        db.content_hash_exists.assert_called_once_with("h1", user_id="bob")

    def test_upsert_dedup_delete_is_scoped_to_writing_owner(self, db):
        """When the writer's own chunk exists, the pre-delete is scoped to that
        owner (own-bucket only), leaving other owners' identical content intact."""
        db.content_hash_exists = MagicMock(return_value=True)

        db.upsert(content_hash="h1", documents=[_doc()], user_id="bob")

        sent_filter = db.index.delete.call_args.kwargs["filter"]
        assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "bob"}}
