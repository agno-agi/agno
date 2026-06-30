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
    # query() returns an object with a ``.matches`` list.
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


# --------------------------------------------------------------------------- #
# Signatures
# --------------------------------------------------------------------------- #


def test_signatures_accept_user_id():
    import inspect

    for method in (
        "insert",
        "async_insert",
        "upsert",
        "async_upsert",
        "search",
        "async_search",
        "delete_by_content_id",
    ):
        params = inspect.signature(getattr(PineconeDb, method)).parameters
        assert "user_id" in params, f"{method} missing user_id"
        # user_id must be LAST and default to None.
        assert list(params)[-1] == "user_id", f"{method} user_id is not last"
        assert params["user_id"].default is None


# --------------------------------------------------------------------------- #
# Write: stamp the owner into metadata
# --------------------------------------------------------------------------- #


def test_upsert_stamps_user_id_into_metadata(db):
    db.content_hash_exists = MagicMock(return_value=False)

    db.upsert(content_hash="h1", documents=[_doc()], user_id="alice")

    vectors = db.index.upsert.call_args.kwargs["vectors"]
    assert len(vectors) == 1
    assert vectors[0]["metadata"][USER_ID_KEY] == "alice"


def test_upsert_shared_bucket_omits_user_id(db):
    db.content_hash_exists = MagicMock(return_value=False)

    db.upsert(content_hash="h1", documents=[_doc()], user_id=None)

    vectors = db.index.upsert.call_args.kwargs["vectors"]
    assert USER_ID_KEY not in vectors[0]["metadata"]


def test_empty_string_user_id_is_shared(db):
    """normalize_user_id collapses "" to None -> shared bucket."""
    db.content_hash_exists = MagicMock(return_value=False)

    db.upsert(content_hash="h1", documents=[_doc()], user_id="")

    vectors = db.index.upsert.call_args.kwargs["vectors"]
    assert USER_ID_KEY not in vectors[0]["metadata"]


def test_caller_metadata_cannot_spoof_owner(db):
    """A caller's own ``user_id`` key in meta_data must not override the owner."""
    db.content_hash_exists = MagicMock(return_value=False)
    doc = Document(content="c", meta_data={"user_id": "attacker"}, name="d")

    db.upsert(content_hash="h1", documents=[doc], user_id="alice")

    vectors = db.index.upsert.call_args.kwargs["vectors"]
    assert vectors[0]["metadata"][USER_ID_KEY] == "alice"


# --------------------------------------------------------------------------- #
# Clobber prevention: id folds in user_id
# --------------------------------------------------------------------------- #


def test_vector_id_folds_in_user_id(db):
    doc = _doc(id="base")
    alice_id = db._vector_id(doc, "h1", "alice")
    bob_id = db._vector_id(doc, "h1", "bob")
    shared_id = db._vector_id(doc, "h1", None)

    # Two users -> two different vector ids (no collision/clobber).
    assert alice_id != bob_id
    # Shared bucket keeps the legacy id (document.id) byte-for-byte.
    assert shared_id == "base"
    assert alice_id != shared_id


def test_upsert_two_users_same_content_distinct_ids(db):
    db.content_hash_exists = MagicMock(return_value=False)

    db.upsert(content_hash="h1", documents=[_doc(id="base")], user_id="alice")
    alice_id = db.index.upsert.call_args.kwargs["vectors"][0]["id"]

    db.upsert(content_hash="h1", documents=[_doc(id="base")], user_id="bob")
    bob_id = db.index.upsert.call_args.kwargs["vectors"][0]["id"]

    assert alice_id != bob_id


# --------------------------------------------------------------------------- #
# Read: own-OR-shared scope filter
# --------------------------------------------------------------------------- #


def test_search_builds_own_or_shared_filter(db):
    db.search(query="q", user_id="alice")

    sent_filter = db.index.query.call_args.kwargs["filter"]
    assert sent_filter == {
        "$or": [
            {USER_ID_KEY: "alice"},
            {USER_ID_KEY: {"$exists": False}},
        ]
    }


def test_search_ands_scope_onto_caller_filter(db):
    caller_filter = {"topic": {"$eq": "t"}}
    db.search(query="q", filters=caller_filter, user_id="alice")

    sent_filter = db.index.query.call_args.kwargs["filter"]
    assert sent_filter == {
        "$and": [
            caller_filter,
            {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]},
        ]
    }


def test_search_admin_has_no_scope(db):
    """user_id=None -> no scope predicate; admin sees everything."""
    db.search(query="q", user_id=None)
    assert db.index.query.call_args.kwargs["filter"] is None

    db.index.query.reset_mock()
    db.search(query="q", filters={"topic": {"$eq": "t"}}, user_id=None)
    assert db.index.query.call_args.kwargs["filter"] == {"topic": {"$eq": "t"}}


async def test_async_search_scopes_too(db):
    await db.async_search(query="q", user_id="alice")
    sent_filter = db.index.query.call_args.kwargs["filter"]
    assert sent_filter == {"$or": [{USER_ID_KEY: "alice"}, {USER_ID_KEY: {"$exists": False}}]}


# --------------------------------------------------------------------------- #
# Delete: scoped to the owner
# --------------------------------------------------------------------------- #


def test_delete_by_content_id_scopes_to_owner(db):
    db.delete_by_content_id("cid-1", user_id="alice")

    sent_filter = db.index.delete.call_args.kwargs["filter"]
    # Scoped delete matches the owner EXACTLY and does NOT OR in the shared
    # bucket — a scoped caller must not be able to wipe org content.
    assert sent_filter == {"content_id": {"$eq": "cid-1"}, USER_ID_KEY: {"$eq": "alice"}}


def test_delete_by_content_id_admin_unscoped(db):
    db.delete_by_content_id("cid-1", user_id=None)

    sent_filter = db.index.delete.call_args.kwargs["filter"]
    assert sent_filter == {"content_id": {"$eq": "cid-1"}}


def test_delete_serverless_falls_back_to_id_delete(db):
    """Serverless rejects delete-by-filter -> resolve ids via query, delete by id."""
    # First delete() call (filter) raises; the id-based delete() then succeeds.
    matched = MagicMock()
    matched.id = "vec-1"
    query_response = MagicMock()
    query_response.matches = [matched]
    db.index.query.return_value = query_response
    db.index.delete.side_effect = [Exception("serverless: filter delete unsupported"), None]

    result = db.delete_by_content_id("cid-1", user_id="alice")

    assert result is True
    # The fallback path queried for ids, then deleted by id.
    last_delete = db.index.delete.call_args
    assert last_delete.kwargs.get("ids") == ["vec-1"]


# --------------------------------------------------------------------------- #
# Upsert dedupe is scoped
# --------------------------------------------------------------------------- #


def test_content_hash_exists_filter_scoped_to_owner(db):
    db.content_hash_exists("h1", user_id="alice")

    sent_filter = db.index.query.call_args.kwargs["filter"]
    assert sent_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}


def test_content_hash_exists_filter_shared(db):
    db.content_hash_exists("h1", user_id=None)

    sent_filter = db.index.query.call_args.kwargs["filter"]
    assert sent_filter == {"content_hash": {"$eq": "h1"}}


def test_upsert_dedupe_deletes_only_owner_chunks(db):
    db.content_hash_exists = MagicMock(return_value=True)

    db.upsert(content_hash="h1", documents=[_doc()], user_id="alice")

    # The dedupe delete must be scoped to alice's content_hash, never global.
    delete_filter = db.index.delete.call_args_list[0].kwargs["filter"]
    assert delete_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}


def test_shared_upsert_dedupe_does_not_wipe_scoped_owners(db):
    """A shared/admin re-ingest (``user_id=None``) must scope its dedupe-delete
    to the shared bucket — pre-fix the None case matched every owner under the
    content_hash and wiped scoped owners' chunks sharing that hash. The existence
    GATE stays any-owner so the shared re-ingest still dedupes against itself."""
    # The dedupe-delete (None case) targets ONLY the shared bucket: no user_id
    # field, so a scoped owner's chunk under the same content_hash is untouched.
    delete_filter = db._content_hash_filter("h1", None, scope_none_to_shared=True)
    assert delete_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}

    # The existence gate (default) stays any-owner so a shared re-ingest still
    # sees prior chunks under the hash regardless of who owns them.
    exists_filter = db._content_hash_filter("h1", None)
    assert exists_filter == {"content_hash": {"$eq": "h1"}}

    # End-to-end through upsert: the shared re-ingest's delete must carry the
    # shared-bucket filter, not a global content_hash-only wipe.
    db.content_hash_exists = MagicMock(return_value=True)
    db.upsert(content_hash="h1", documents=[_doc()], user_id=None)
    sent = db.index.delete.call_args_list[0].kwargs["filter"]
    assert sent == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$exists": False}}


async def test_async_upsert_dedupe_deletes_only_owner_chunks(db):
    """async_upsert reaches _delete_by_content_hash through asyncio.to_thread,
    passing user_id positionally — pin that the dedupe stays scoped to alice."""
    db.content_hash_exists = MagicMock(return_value=True)
    doc = _doc(id="base")

    async def _async_embed(embedder=None):
        doc.embedding = [0.1] * TEST_DIMENSION

    doc.async_embed = _async_embed

    await db.async_upsert(content_hash="h1", documents=[doc], user_id="alice")

    delete_filter = db.index.delete.call_args_list[0].kwargs["filter"]
    assert delete_filter == {"content_hash": {"$eq": "h1"}, USER_ID_KEY: {"$eq": "alice"}}


# --------------------------------------------------------------------------- #
# update_metadata must not let a caller reassign the owner
# --------------------------------------------------------------------------- #


def test_update_metadata_protects_owner(db):
    match = MagicMock()
    match.id = "vec-1"
    match.metadata = {"content_id": "cid-1", USER_ID_KEY: "alice", "x": 1}
    query_response = MagicMock()
    query_response.matches = [match]
    db.index.query.return_value = query_response

    db.update_metadata("cid-1", {"x": 2, USER_ID_KEY: "attacker"})

    updated = db.index.update.call_args.kwargs["vectors"][0]["metadata"]
    assert updated[USER_ID_KEY] == "alice"
    assert updated["x"] == 2
