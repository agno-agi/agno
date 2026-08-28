"""Unit tests for Weaviate per-user isolation.

The owner lives in a top-level ``user_id`` property and NULL is the shared bucket. The
clients are mocked, so these tests assert on the filter handed to the collection query.
"""

import uuid
from hashlib import md5
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.search import SearchType
from agno.vectordb.weaviate import Weaviate

from .conftest import DeterministicEmbedder

TEST_COLLECTION = "IsolationTest"
USER_ID_KEY = Weaviate.USER_ID_KEY


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
def weaviate_db(mock_weaviate_client, mock_async_weaviate_client):
    """Create a Weaviate instance with mocked sync and async clients."""
    db = Weaviate(
        collection=TEST_COLLECTION,
        local=True,
        embedder=DeterministicEmbedder(),
        client=mock_weaviate_client,
        search_type=SearchType.vector,
    )
    # The mocked client cannot answer the live-schema probe, so prime the owner-property gate.
    db._owner_property_exists = True
    return db


def _alice_docs():
    return [Document(name="alice-salary", content="Alice salary is 180k secret")]


def _bob_docs():
    return [Document(name="bob-salary", content="Bob salary is 215k secret")]


def _shared_docs():
    return [Document(name="company-holidays", content="The office salary policy is shared")]


def _collection(client):
    return client.collections.get.return_value


class TestWriteStampsOwner:
    """Inserts stamp the owner on ``user_id``; None and omitted land in the shared bucket."""

    def test_explicit_user_id_persisted(self, weaviate_db, mock_weaviate_client):
        weaviate_db.insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        props = _collection(mock_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] == "alice"

    def test_none_user_id_persisted_as_null(self, weaviate_db, mock_weaviate_client):
        weaviate_db.insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        props = _collection(mock_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] is None

    def test_user_id_omitted_defaults_to_null(self, weaviate_db, mock_weaviate_client):
        weaviate_db.insert(content_hash="h1", documents=_shared_docs())
        props = _collection(mock_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] is None


class TestOwnerFoldedId:
    """The owner is folded into the record id, so identical content from two owners gets distinct uuids."""

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


class TestSearchScope:
    """A scoped search filters own-or-shared; an admin search (user_id=None) applies no filter."""

    def test_scoped_vector_search_is_own_or_shared(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search("salary", limit=10, user_id="alice")
        sent = _collection(mock_weaviate_client).query.near_vector.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
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
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]

    def test_hybrid_search_scoped(self, weaviate_db, mock_weaviate_client):
        weaviate_db.search_type = SearchType.hybrid
        weaviate_db.search("salary", limit=10, user_id="alice")
        sent = _collection(mock_weaviate_client).query.hybrid.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]


class TestUpsertDedupScope:
    """The upsert dedup delete is scoped to the writing owner, so it never wipes another owner's rows."""

    def test_owner_upsert_dedup_deletes_only_owner(self, weaviate_db, mock_weaviate_client):
        weaviate_db.content_hash_exists = MagicMock(return_value=True)
        weaviate_db.upsert(content_hash="h", documents=_alice_docs(), user_id="alice")
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "Equal", "alice"),
        ]

    def test_shared_upsert_dedup_deletes_only_shared_bucket(self, weaviate_db, mock_weaviate_client):
        weaviate_db.content_hash_exists = MagicMock(return_value=True)
        weaviate_db.upsert(content_hash="h", documents=_shared_docs(), user_id=None)
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "IsNull", True),
        ]

    def test_upsert_dedup_check_scoped_to_writing_owner(self, weaviate_db):
        weaviate_db.content_hash_exists = MagicMock(return_value=False)
        weaviate_db.upsert(content_hash="h", documents=_bob_docs(), user_id="bob")
        weaviate_db.content_hash_exists.assert_called_once_with("h", user_id="bob")


class TestDeleteScope:
    """delete_by_content_id restricts to the owner; only None spans all owners."""

    def test_scoped_delete_matches_owner_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db.delete_by_content_id("doc-1", user_id="bob")
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_id", "Equal", "doc-1"),
            (USER_ID_KEY, "Equal", "bob"),
        ]

    def test_unscoped_delete_is_content_id_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db.delete_by_content_id("doc-1", user_id=None)
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterValue"
        assert _leaves(where) == [("content_id", "Equal", "doc-1")]


class TestDedupScope:
    """_delete_by_content_hash clears only the given owner; None clears only the shared (null) bucket."""

    def test_scoped_delete_matches_owner_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db._delete_by_content_hash("h", user_id="alice")
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "Equal", "alice"),
        ]

    def test_none_delete_matches_shared_bucket_only(self, weaviate_db, mock_weaviate_client):
        weaviate_db._delete_by_content_hash("h", user_id=None)
        where = _collection(mock_weaviate_client).data.delete_many.call_args.kwargs["where"]
        assert _combinator(where) == "_FilterAnd"
        assert _leaves(where) == [
            ("content_hash", "Equal", "h"),
            (USER_ID_KEY, "IsNull", True),
        ]


class TestEmptyUserIdRejected:
    """Empty / whitespace-only user_id folds to the shared null bucket under FIELD tokenization."""

    @pytest.mark.parametrize("bad_id", ["", " ", "   ", "\t", "\n"])
    def test_insert_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            weaviate_db.insert(content_hash="h1", documents=_alice_docs(), user_id=bad_id)

    @pytest.mark.parametrize("bad_id", ["", " ", "   ", "\t", "\n"])
    def test_search_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            weaviate_db.search("salary", limit=10, user_id=bad_id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_id", ["", " ", "\t"])
    async def test_async_insert_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            await weaviate_db.async_insert(content_hash="h1", documents=_alice_docs(), user_id=bad_id)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_id", ["", " ", "\t"])
    async def test_async_search_rejects(self, weaviate_db, bad_id):
        with pytest.raises(ValueError):
            await weaviate_db.async_search("salary", limit=10, user_id=bad_id)


class TestAsyncIsolation:
    """The async path must stamp the owner and scope reads identically."""

    @pytest.mark.asyncio
    async def test_async_insert_stamps_owner(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_insert(content_hash="h1", documents=_alice_docs(), user_id="alice")
        props = _collection(mock_async_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] == "alice"

    @pytest.mark.asyncio
    async def test_async_insert_none_is_shared(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_insert(content_hash="h1", documents=_shared_docs(), user_id=None)
        props = _collection(mock_async_weaviate_client).data.insert.call_args.kwargs["properties"]
        assert props[USER_ID_KEY] is None

    @pytest.mark.asyncio
    async def test_async_search_scoped(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_search("salary", limit=10, user_id="alice")
        sent = _collection(mock_async_weaviate_client).query.near_vector.call_args.kwargs["filters"]
        assert _combinator(sent) == "_FilterOr"
        assert _leaves(sent) == [
            (USER_ID_KEY, "Equal", "alice"),
            (USER_ID_KEY, "IsNull", True),
        ]

    @pytest.mark.asyncio
    async def test_async_admin_search_has_no_scope(self, weaviate_db, mock_async_weaviate_client):
        await weaviate_db.async_search("salary", limit=10, user_id=None)
        assert _collection(mock_async_weaviate_client).query.near_vector.call_args.kwargs["filters"] is None
