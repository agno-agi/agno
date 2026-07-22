"""Weaviate per-user RAG isolation contract (pure unit test, no server).

Weaviate stores ``user_id`` as a first-class TEXT property (FIELD tokenization so
the scope filter matches the owner exactly). Scoped searches filter on
``user_id == caller OR user_id IS NULL`` so admin-uploaded shared content stays
discoverable; ``user_id=None`` at search time applies no scope (admin view).

This suite mocks the Weaviate client/collection so it runs with NO server. The
isolation logic lives in the values the adapter writes and the ``Filter`` it
builds, so we introspect those directly:

* inserted object properties -> the stamped ``user_id`` and the owner-folded uuid,
* the ``Filter`` handed to ``query.near_vector`` / ``data.delete_many`` -> flattened
  to ``(target, operator, value)`` leaves plus the AND/OR combinator.

Caveat (stated honestly): a mocked collection cannot prove Weaviate's engine
*enforces* the filter — only that the adapter builds the own-OR-shared / owner-scoped
predicate. The engine's semantics are exercised by the server-backed suites.
"""

import uuid
from hashlib import md5
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

weaviate = pytest.importorskip("weaviate")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.search import SearchType  # noqa: E402
from agno.vectordb.weaviate import Weaviate  # noqa: E402

TEST_COLLECTION = "IsolationTest"
USER_ID_KEY = Weaviate.USER_ID_KEY


# --- Filter introspection -------------------------------------------------
# weaviate Filter nodes: a leaf ``_FilterValue`` exposes .target/.operator/.value;
# a boolean ``_FilterAnd`` / ``_FilterOr`` exposes .filters. We flatten to the
# isolation-determining shape so assertions bite on the real predicate.


def _leaves(f):
    """Flatten a Filter into ordered (target, operator, value) leaf tuples."""
    if f is None:
        return []
    if hasattr(f, "filters"):
        out = []
        for sub in f.filters:
            out.extend(_leaves(sub))
        return out
    return [(f.target, f.operator.value, f.value)]


def _combinator(f):
    """The top-level node kind: _FilterOr, _FilterAnd or _FilterValue."""
    return type(f).__name__


# --- Fakes ----------------------------------------------------------------


def _empty_response():
    resp = MagicMock()
    resp.objects = []
    return resp


def _make_collection():
    collection = MagicMock()
    collection.query.near_vector.return_value = _empty_response()
    collection.query.bm25.return_value = _empty_response()
    collection.query.hybrid.return_value = _empty_response()
    collection.query.fetch_objects.return_value = _empty_response()
    delete_result = MagicMock()
    delete_result.successful = 1
    collection.data.delete_many.return_value = delete_result
    return collection


def _make_client(collection):
    client = MagicMock()
    client.is_connected.return_value = True
    client.is_ready.return_value = True
    client.collections.get.return_value = collection
    client.collections.exists.return_value = True
    return client


def _make_async_collection():
    collection = MagicMock()
    collection.query.near_vector = AsyncMock(return_value=_empty_response())
    collection.query.bm25 = AsyncMock(return_value=_empty_response())
    collection.query.hybrid = AsyncMock(return_value=_empty_response())
    collection.data.insert = AsyncMock()
    return collection


def _make_async_client(collection):
    client = MagicMock()
    client.is_connected.return_value = True
    client.is_ready = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.collections.get.return_value = collection
    client.collections.exists = AsyncMock(return_value=True)
    return client


class _Env:
    """Bundle of the db under test plus the mocked sync/async collections."""

    def __init__(self, db, sync_collection, async_collection):
        self.db = db
        self.sync_collection = sync_collection
        self.async_collection = async_collection


@pytest.fixture
def mock_embedder():
    """A tiny embedder needing no network; batch path disabled for determinism."""
    mock = MagicMock()
    mock.dimensions = 8
    mock.enable_batch = False
    vec = [0.1] * 8
    mock.get_embedding.return_value = vec
    mock.get_embedding_and_usage.return_value = (vec, {"total_tokens": 1})
    mock.async_get_embedding_and_usage = AsyncMock(return_value=(vec, {"total_tokens": 1}))
    return mock


@pytest.fixture
def env(mock_embedder):
    """Weaviate wired to mocked clients; a real connection would fail loudly."""
    sync_collection = _make_collection()
    sync_client = _make_client(sync_collection)
    async_collection = _make_async_collection()
    async_client = _make_async_client(async_collection)

    with (
        patch.object(weaviate, "connect_to_local", side_effect=AssertionError("must not open a real connection")),
        patch.object(
            weaviate, "connect_to_weaviate_cloud", side_effect=AssertionError("must not open a real connection")
        ),
        patch.object(weaviate, "use_async_with_local", return_value=async_client),
    ):
        db = Weaviate(
            collection=TEST_COLLECTION,
            local=True,
            embedder=mock_embedder,
            client=sync_client,
            search_type=SearchType.vector,
        )
        yield _Env(db, sync_collection, async_collection)


def _alice_docs():
    return [Document(name="alice-salary", content="Alice salary is 180k secret")]


def _bob_docs():
    return [Document(name="bob-salary", content="Bob salary is 215k secret")]


def _shared_docs():
    return [Document(name="company-holidays", content="The office salary policy is shared")]


def _last_insert(collection):
    return collection.data.insert.call_args


class TestWriteStampsOwner:
    """Inserts stamp the owner on the top-level ``user_id`` property; None (and
    omitted) land in the shared bucket (property is None)."""

    def test_explicit_user_id_persisted(self, env):
        env.db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        props = _last_insert(env.sync_collection).kwargs["properties"]
        assert props[USER_ID_KEY] == "alice"

    def test_none_user_id_persisted_as_null(self, env):
        env.db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        props = _last_insert(env.sync_collection).kwargs["properties"]
        assert props[USER_ID_KEY] is None

    def test_user_id_omitted_defaults_to_null(self, env):
        env.db.insert(content_hash="h1", documents=_shared_docs())
        props = _last_insert(env.sync_collection).kwargs["properties"]
        assert props[USER_ID_KEY] is None


class TestOwnerFoldedId:
    """Two owners uploading byte-identical content get DISTINCT uuids (the owner
    is folded into the id), so one insert never clobbers the other. The shared
    (user_id=None) write keeps the base (owner-free) uuid."""

    def _insert_uuid(self, env, user_id):
        env.sync_collection.data.insert.reset_mock()
        env.db.insert(
            content_hash="shared_hash",
            documents=[Document(name="doc", content="identical secret body")],
            user_id=user_id,
        )
        return _last_insert(env.sync_collection).kwargs["uuid"]

    def test_two_owners_get_distinct_uuids(self, env):
        alice_uuid = self._insert_uuid(env, "alice")
        bob_uuid = self._insert_uuid(env, "bob")
        assert alice_uuid != bob_uuid

    def test_shared_write_keeps_base_uuid(self, env):
        shared_uuid = self._insert_uuid(env, None)
        # Base (owner-free) uuid the adapter derives when user_id is None.
        content = "identical secret body"
        base_id = md5(content.encode()).hexdigest()
        record_id = md5(f"{base_id}_shared_hash".encode()).hexdigest()
        assert shared_uuid == uuid.UUID(hex=record_id[:32])

    def test_owner_uuid_differs_from_shared(self, env):
        alice_uuid = self._insert_uuid(env, "alice")
        shared_uuid = self._insert_uuid(env, None)
        assert alice_uuid != shared_uuid


class TestSearchScope:
    """A scoped search filters own-OR-shared (user_id == caller OR IS NULL); an
    admin search (user_id=None) applies no filter. This IS the read contract."""

    def test_scoped_vector_search_is_own_or_shared(self, env):
        env.db.search("salary", limit=10, user_id="alice")
        sent = env.sync_collection.query.near_vector.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]

    def test_scoped_search_never_names_other_owner(self, env):
        env.db.search("salary", limit=10, user_id="alice")
        sent = env.sync_collection.query.near_vector.call_args.kwargs["filters"]
        assert all(value != "bob" for _, _, value in _leaves(sent))

    def test_admin_search_has_no_scope(self, env):
        env.db.search("salary", limit=10, user_id=None)
        assert env.sync_collection.query.near_vector.call_args.kwargs["filters"] is None

    def test_keyword_search_scoped(self, env):
        env.db.search_type = SearchType.keyword
        env.db.search("salary", limit=10, user_id="alice")
        sent = env.sync_collection.query.bm25.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]

    def test_hybrid_search_scoped(self, env):
        env.db.search_type = SearchType.hybrid
        env.db.search("salary", limit=10, user_id="alice")
        sent = env.sync_collection.query.hybrid.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]


class TestScopedDedup:
    """The upsert dedup delete is scoped to the writing owner, so re-ingesting
    shared content never wipes an owner's identical-content row (and vice versa)."""

    def test_owner_upsert_dedup_deletes_only_owner(self, env):
        env.db.content_hash_exists = MagicMock(return_value=True)
        env.db.upsert(content_hash="h", documents=_alice_docs(), user_id="alice")
        where = env.sync_collection.data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "Equal", "alice"),
        ]

    def test_shared_upsert_dedup_deletes_only_shared_bucket(self, env):
        env.db.content_hash_exists = MagicMock(return_value=True)
        env.db.upsert(content_hash="h", documents=_shared_docs(), user_id=None)
        where = env.sync_collection.data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "IsNull", True),
        ]

    def test_upsert_dedup_check_scoped_to_writing_owner(self, env):
        env.db.content_hash_exists = MagicMock(return_value=False)
        env.db.upsert(content_hash="h", documents=_bob_docs(), user_id="bob")
        env.db.content_hash_exists.assert_called_once_with("h", user_id="bob")


class TestDeleteByContentIdScope:
    """delete_by_content_id restricts to the owner; only None spans all owners."""

    def test_scoped_delete_matches_owner_only(self, env):
        env.db.delete_by_content_id("doc-1", user_id="bob")
        where = env.sync_collection.data.delete_many.call_args.kwargs["where"]
        # ANDs the owner on: a scoped caller cannot wipe another owner's chunks,
        # and does NOT OR in the shared bucket.
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_id", "Equal", "doc-1"),
            (USER_ID_KEY, "Equal", "bob"),
        ]

    def test_unscoped_delete_is_content_id_only(self, env):
        env.db.delete_by_content_id("doc-1", user_id=None)
        where = env.sync_collection.data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterValue"
        assert _leaves(where) == [("content_id", "Equal", "doc-1")]


class TestDeleteByContentHashScope:
    """_delete_by_content_hash scoped to an owner clears only that owner; None
    clears ONLY the shared (null) bucket, never other owners' identical rows."""

    def test_scoped_delete_matches_owner_only(self, env):
        env.db._delete_by_content_hash("h", user_id="alice")
        where = env.sync_collection.data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "Equal", "alice"),
        ]

    def test_none_delete_matches_shared_bucket_only(self, env):
        env.db._delete_by_content_hash("h", user_id=None)
        where = env.sync_collection.data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "IsNull", True),
        ]


class TestEmptyUserIdRejected:
    """Empty / whitespace-only user_id folds to the null bucket under FIELD
    tokenization, leaking the row to every caller. Writes and reads must reject it."""

    @pytest.mark.parametrize("bad_id", ["", " ", "   ", "\t", "\n"])
    def test_insert_rejects(self, env, bad_id):
        with pytest.raises(ValueError):
            env.db.insert(content_hash="h1", documents=_alice_docs(), user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "   ", "\t", "\n"])
    def test_search_rejects(self, env, bad_id):
        with pytest.raises(ValueError):
            env.db.search("salary", limit=10, user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "\t"])
    async def test_async_insert_rejects(self, env, bad_id):
        with pytest.raises(ValueError):
            await env.db.async_insert(content_hash="h1", documents=_alice_docs(), user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "\t"])
    async def test_async_search_rejects(self, env, bad_id):
        with pytest.raises(ValueError):
            await env.db.async_search("salary", limit=10, user_id=bad_id)


class TestAsyncIsolation:
    """The async path must stamp the owner and scope reads identically."""

    async def test_async_insert_stamps_owner(self, env):
        await env.db.async_insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        props = env.async_collection.data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] == "alice"

    async def test_async_insert_none_is_shared(self, env):
        await env.db.async_insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        props = env.async_collection.data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] is None

    async def test_async_search_scoped(self, env):
        await env.db.async_search("salary", limit=10, user_id="alice")
        sent = env.async_collection.query.near_vector.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]

    async def test_async_admin_search_has_no_scope(self, env):
        await env.db.async_search("salary", limit=10, user_id=None)
        assert env.async_collection.query.near_vector.call_args.kwargs["filters"] is None
