"""Weaviate per-user RAG isolation contract.

Weaviate stores ``user_id`` as a first-class TEXT property (FIELD tokenization
so the scope filter matches the owner exactly). Scoped searches filter on
``user_id == caller OR user_id IS NULL`` so admin-uploaded shared content stays
discoverable; ``user_id=None`` at search time applies no scope (admin view).

The client/collection are mocked so no server is needed. The isolation logic
lives in the values the adapter writes and the ``Filter`` it builds, so we
assert on the inserted object properties (the stamped ``user_id`` and the
owner-folded uuid) and on the ``Filter`` handed to ``query.near_vector`` /
``data.delete_many``, flattened to ``(target, operator, value)`` leaves.
"""

import uuid
from hashlib import md5
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Weaviate
from agno.vectordb.weaviate.weaviate import USER_ID_PROPERTY

TEST_COLLECTION = "IsolationTest"


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
    """The top-level Filter node kind: _FilterOr, _FilterAnd or _FilterValue."""
    return type(f).__name__


def _empty_response():
    resp = MagicMock()
    resp.objects = []
    return resp


@pytest.fixture
def mock_embedder():
    """A tiny embedder that needs no network or API key."""
    mock = MagicMock()
    mock.dimensions = 8
    mock.enable_batch = False
    vec = [0.1] * 8
    mock.get_embedding.return_value = vec
    mock.get_embedding_and_usage.return_value = (vec, {"total_tokens": 1})
    mock.async_get_embedding_and_usage = AsyncMock(return_value=(vec, {"total_tokens": 1}))
    return mock


@pytest.fixture
def mock_weaviate_client():
    """Create a mock Weaviate client."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.is_ready.return_value = True
    client.collections.exists.return_value = True

    collection = MagicMock()
    client.collections.get.return_value = collection
    collection.query.near_vector.return_value = _empty_response()
    collection.query.bm25.return_value = _empty_response()
    collection.query.hybrid.return_value = _empty_response()
    collection.query.fetch_objects.return_value = _empty_response()
    collection.data.delete_many.return_value = MagicMock(successful=1)
    return client


@pytest.fixture
def mock_async_weaviate_client():
    """Create a mock async Weaviate client."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.is_ready = AsyncMock(return_value=True)
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.collections.exists = AsyncMock(return_value=True)

    collection = MagicMock()
    client.collections.get.return_value = collection
    collection.query.near_vector = AsyncMock(return_value=_empty_response())
    collection.query.bm25 = AsyncMock(return_value=_empty_response())
    collection.query.hybrid = AsyncMock(return_value=_empty_response())
    collection.data.insert = AsyncMock()

    with patch("weaviate.use_async_with_local", return_value=client):
        yield client


@pytest.fixture
def weaviate_db(mock_weaviate_client, mock_async_weaviate_client, mock_embedder):
    """Create a Weaviate instance with mocked sync and async clients."""
    return Weaviate(
        collection=TEST_COLLECTION,
        local=True,
        embedder=mock_embedder,
        client=mock_weaviate_client,
        search_type=SearchType.vector,
    )


def _alice_docs():
    return [Document(name="alice-salary", content="Alice salary is 180k secret")]


def _bob_docs():
    return [Document(name="bob-salary", content="Bob salary is 215k secret")]


def _shared_docs():
    return [Document(name="company-holidays", content="The office salary policy is shared")]


def _collection(client):
    return client.collections.get.return_value


class TestWriteStampsOwner:
    """Inserts stamp the owner on the top-level ``user_id`` property; None (and
    omitted) land in the shared bucket (property is None)."""

    def test_explicit_user_id_persisted(self, weaviate_db, mock_weaviate_client):
        weaviate_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        props = _collection(mock_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_PROPERTY] == "alice"

    def test_none_user_id_persisted_as_null(self, weaviate_db, mock_weaviate_client):
        weaviate_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        props = _collection(mock_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_PROPERTY] is None

    def test_user_id_omitted_defaults_to_null(self, weaviate_db, mock_weaviate_client):
        weaviate_db.insert(content_hash="h1", documents=_shared_docs())
        props = _collection(mock_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_PROPERTY] is None


class TestOwnerFoldedId:
    """Two owners uploading byte-identical content get DISTINCT uuids (the owner
    is folded into the id), so one insert never clobbers the other. The shared
    (user_id=None) write keeps the base (owner-free) uuid."""

    def _insert_uuid(self, weaviate_db, mock_weaviate_client, user_id):
        _collection(mock_weaviate_client).data.insert.reset_mock()
        weaviate_db.insert(
            content_hash="shared_hash",
            documents=[Document(name="doc", content="identical secret body")],
            user_id=user_id,
        )
        return _collection(mock_weaviate_client).data.insert.call_args.kwargs["uuid"]

    def test_two_owners_get_distinct_uuids(self, weaviate_db, mock_weaviate_client):
        alice_uuid = self._insert_uuid(weaviate_db, mock_weaviate_client, "alice")
        bob_uuid = self._insert_uuid(weaviate_db, mock_weaviate_client, "bob")
        assert alice_uuid != bob_uuid

    def test_shared_write_keeps_base_uuid(self, weaviate_db, mock_weaviate_client):
        shared_uuid = self._insert_uuid(weaviate_db, mock_weaviate_client, None)
        # Base (owner-free) uuid the adapter derives when user_id is None.
        content = "identical secret body"
        base_id = md5(content.encode()).hexdigest()
        record_id = md5(f"{base_id}_shared_hash".encode()).hexdigest()
        assert shared_uuid == uuid.UUID(hex=record_id[:32])

    def test_owner_uuid_differs_from_shared(self, weaviate_db, mock_weaviate_client):
        alice_uuid = self._insert_uuid(weaviate_db, mock_weaviate_client, "alice")
        shared_uuid = self._insert_uuid(weaviate_db, mock_weaviate_client, None)
        assert alice_uuid != shared_uuid

    def test_owner_boundary_cannot_be_shifted(self, weaviate_db):
        """The base parts are collapsed to a fixed-length digest before the owner
        is folded in, so the '_' boundary cannot slide. Folding the owner straight
        onto the raw parts instead would let ("h", "alice") and ("h_alice", None)
        join to one string and land on ONE uuid, so a crafted owner overwrites the
        shared chunk."""
        assert weaviate_db._scoped_record_id("doc", "h", "alice") != weaviate_db._scoped_record_id(
            "doc", "h_alice", None
        )


class TestSearchScope:
    """A scoped search filters own-OR-shared (user_id == caller OR IS NULL); an
    admin search (user_id=None) applies no filter."""

    def test_scoped_vector_search_is_own_or_shared(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search("salary", limit=10, user_id="alice")
        sent = _collection(mock_weaviate_client).query.near_vector.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_PROPERTY, "Equal", "alice"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]

    def test_scoped_search_never_names_other_owner(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search("salary", limit=10, user_id="alice")
        sent = _collection(mock_weaviate_client).query.near_vector.call_args.kwargs["filters"]
        assert all(value != "bob" for _, _, value in _leaves(sent))

    def test_admin_search_has_no_scope(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search("salary", limit=10, user_id=None)
        assert _collection(mock_weaviate_client).query.near_vector.call_args.kwargs["filters"] is None

    def test_keyword_search_scoped(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search_type = SearchType.keyword
        weaviate_db.search("salary", limit=10, user_id="alice")
        sent = _collection(mock_weaviate_client).query.bm25.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_PROPERTY, "Equal", "alice"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]

    def test_hybrid_search_scoped(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search_type = SearchType.hybrid
        weaviate_db.search("salary", limit=10, user_id="alice")
        sent = _collection(mock_weaviate_client).query.hybrid.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_PROPERTY, "Equal", "alice"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]


class TestScopedDedup:
    """The upsert dedup delete is scoped to the writing owner, so re-ingesting
    shared content never wipes an owner's identical-content row (and vice versa)."""

    def test_owner_upsert_dedup_deletes_only_owner(self, weaviate_db, mock_weaviate_client):
        weaviate_db.content_hash_exists = MagicMock(return_value=True)
        weaviate_db.upsert(content_hash="h", documents=_alice_docs(), user_id="alice")
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_PROPERTY, "Equal", "alice"),
        ]

    def test_shared_upsert_dedup_deletes_only_shared_bucket(self, weaviate_db, mock_weaviate_client):
        weaviate_db.content_hash_exists = MagicMock(return_value=True)
        weaviate_db.upsert(content_hash="h", documents=_shared_docs(), user_id=None)
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]

    def test_upsert_dedup_check_scoped_to_writing_owner(self, weaviate_db):
        weaviate_db.content_hash_exists = MagicMock(return_value=False)
        weaviate_db.upsert(content_hash="h", documents=_bob_docs(), user_id="bob")
        weaviate_db.content_hash_exists.assert_called_once_with("h", user_id="bob")


class TestDeleteByContentIdScope:
    """delete_by_content_id restricts to the owner; only None spans all owners."""

    def test_scoped_delete_matches_owner_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db.delete_by_content_id("doc-1", user_id="bob")
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        # ANDs the owner on: a scoped caller cannot wipe another owner's chunks,
        # and does NOT OR in the shared bucket.
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_id", "Equal", "doc-1"),
            (USER_ID_PROPERTY, "Equal", "bob"),
        ]

    def test_unscoped_delete_is_content_id_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db.delete_by_content_id("doc-1", user_id=None)
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterValue"
        assert _leaves(where) == [("content_id", "Equal", "doc-1")]


class TestDeleteByContentHashScope:
    """_delete_by_content_hash scoped to an owner clears only that owner; None
    clears ONLY the shared (null) bucket, never other owners' identical rows."""

    def test_scoped_delete_matches_owner_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db._delete_by_content_hash("h", user_id="alice")
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_PROPERTY, "Equal", "alice"),
        ]

    def test_none_delete_matches_shared_bucket_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db._delete_by_content_hash("h", user_id=None)
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]


class TestContentHashExistsScope:
    """content_hash_exists is the guard half of the upsert dedup pair, so it means
    what _delete_by_content_hash means: a set owner checks that owner's chunks and
    None checks the shared (null) bucket alone, never every owner's rows."""

    def _store(self, client, rows):
        """Answer fetch_objects from ``rows`` — a list of ``(content_hash, user_id)``
        — by applying the filter leaves the adapter built, the way the server would."""

        def fetch_objects(limit=None, filters=None, **kwargs):
            wanted = {}
            for target, operator, value in _leaves(filters):
                wanted[target] = None if operator == "IsNull" else value
            matched = [
                row for row in rows if row[0] == wanted.get("content_hash") and row[1] == wanted.get(USER_ID_PROPERTY)
            ]
            response = MagicMock()
            response.objects = matched[:limit] if limit else matched
            return response

        _collection(client).query.fetch_objects.side_effect = fetch_objects

    def test_scoped_check_matches_owner_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db.content_hash_exists("h", user_id="alice")
        where = _collection(mock_weaviate_client).query.fetch_objects.call_args.kwargs["filters"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_PROPERTY, "Equal", "alice"),
        ]

    def test_none_check_matches_shared_bucket_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db.content_hash_exists("h", user_id=None)
        where = _collection(mock_weaviate_client).query.fetch_objects.call_args.kwargs["filters"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]

    def test_none_check_sees_the_shared_row(self, weaviate_db, mock_weaviate_client):
        self._store(mock_weaviate_client, [("h", None)])
        assert weaviate_db.content_hash_exists("h", user_id=None) is True

    def test_none_check_does_not_see_a_privately_owned_row(self, weaviate_db, mock_weaviate_client):
        """Alice privately holds this content. If None matched her row, a shared
        publish of the same bytes would be judged a duplicate and silently skipped,
        and the shared bucket would never receive it."""
        self._store(mock_weaviate_client, [("h", "alice")])
        assert weaviate_db.content_hash_exists("h", user_id=None) is False
        assert weaviate_db.content_hash_exists("h", user_id="alice") is True


class TestEmptyUserIdRejected:
    """Empty / whitespace-only user_id folds to the null bucket under FIELD
    tokenization, leaking the row to every caller. Writes and reads must reject it."""

    @pytest.mark.parametrize("bad_id", ["", " ", "   ", "\t", "\n"])
    def test_insert_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            weaviate_db.insert(content_hash="h1", documents=_alice_docs(), user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "   ", "\t", "\n"])
    def test_search_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            weaviate_db.search("salary", limit=10, user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "\t"])
    async def test_async_insert_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            await weaviate_db.async_insert(content_hash="h1", documents=_alice_docs(), user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "\t"])
    async def test_async_search_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            await weaviate_db.async_search("salary", limit=10, user_id=bad_id)


class TestAsyncIsolation:
    """The async path must stamp the owner and scope reads identically."""

    async def test_async_insert_stamps_owner(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        props = _collection(mock_async_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_PROPERTY] == "alice"

    async def test_async_insert_none_is_shared(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        props = _collection(mock_async_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_PROPERTY] is None

    async def _async_insert_uuid(self, weaviate_db, mock_async_weaviate_client, user_id):
        _collection(mock_async_weaviate_client).data.insert.reset_mock()
        await weaviate_db.async_insert(
            content_hash="shared_hash",
            documents=[Document(name="doc", content="identical secret body")],
            user_id=user_id,
        )
        return _collection(mock_async_weaviate_client).data.insert.call_args.kwargs["uuid"]

    async def test_async_two_owners_get_distinct_uuids(self, weaviate_db, mock_async_weaviate_client):
        # The async insert builds its own uuid, so it needs the owner fold proven
        # here too - a sync-only assertion lets the two paths drift apart.
        alice_uuid = await self._async_insert_uuid(weaviate_db, mock_async_weaviate_client, "alice")
        bob_uuid = await self._async_insert_uuid(weaviate_db, mock_async_weaviate_client, "bob")
        assert alice_uuid != bob_uuid

    async def test_async_shared_write_keeps_base_uuid(self, weaviate_db, mock_async_weaviate_client):
        shared_uuid = await self._async_insert_uuid(weaviate_db, mock_async_weaviate_client, None)
        base_id = md5(b"identical secret body").hexdigest()
        record_id = md5(f"{base_id}_shared_hash".encode()).hexdigest()
        assert shared_uuid == uuid.UUID(hex=record_id[:32])

    async def test_async_owner_uuid_differs_from_shared(self, weaviate_db, mock_async_weaviate_client):
        alice_uuid = await self._async_insert_uuid(weaviate_db, mock_async_weaviate_client, "alice")
        shared_uuid = await self._async_insert_uuid(weaviate_db, mock_async_weaviate_client, None)
        assert alice_uuid != shared_uuid

    async def test_async_search_scoped(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_search("salary", limit=10, user_id="alice")
        sent = _collection(mock_async_weaviate_client).query.near_vector.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_PROPERTY, "Equal", "alice"),
            (USER_ID_PROPERTY, "IsNull", True),
        ]

    async def test_async_admin_search_has_no_scope(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_search("salary", limit=10, user_id=None)
        assert _collection(mock_async_weaviate_client).query.near_vector.call_args.kwargs["filters"] is None
