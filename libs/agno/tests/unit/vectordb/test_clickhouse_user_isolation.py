"""Unit tests for ClickHouse per-user isolation.

The owner lives in a ``user_id`` String column and ``""`` is the shared bucket. The clients
are mocked, so the assertions run against the captured SQL and bound parameters.
"""

from hashlib import md5
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.document import Document
from agno.vectordb.clickhouse import Clickhouse
from agno.vectordb.clickhouse.clickhousedb import SHARED_OWNER
from agno.vectordb.search import SearchType

from .conftest import DeterministicEmbedder

# The columns the adapter writes; indices are resolved from the captured ``column_names``.
INSERT_COLUMNS = [
    "id",
    "name",
    "meta_data",
    "filters",
    "content",
    "content_id",
    "embedding",
    "usage",
    "content_hash",
    "user_id",
]


def _doc(name: str, content: str, content_id: str = None) -> Document:
    doc = Document(name=name, content=content)
    doc.content_id = content_id if content_id is not None else name
    doc.embedding = DeterministicEmbedder().get_embedding(content)
    return doc


def _empty_result():
    """A query result the search/exists paths can iterate without a server."""
    result = MagicMock()
    result.result_rows = []
    result.first_row = None
    return result


@pytest.fixture
def clickhouse_db():
    """Build a Clickhouse instance backed by mocked ``.client`` / ``.async_client``."""
    client = MagicMock()
    client.query.return_value = _empty_result()
    async_client = AsyncMock()
    async_client.command.return_value = None
    async_client.query.return_value = _empty_result()
    db = Clickhouse(
        table_name="iso_tbl",
        host="localhost",
        database_name="iso_db",
        embedder=DeterministicEmbedder(),
        client=client,
        asyncclient=async_client,
    )
    # The mocked client cannot answer the schema probe, so prime the owner-column gate.
    db._owner_column_exists = True
    return db


def _insert_row(client):
    """The single row + resolved column index map from a captured insert."""
    call = client.insert.call_args
    rows = call.args[1]
    column_names = call.kwargs["column_names"]
    return rows[0], {name: i for i, name in enumerate(column_names)}


def _owner_of(client) -> str:
    row, idx = _insert_row(client)
    return row[idx["user_id"]]


def _id_of(client) -> str:
    row, idx = _insert_row(client)
    return row[idx["id"]]


class TestSchema:
    """Pin the supported search type."""

    def test_get_supported_search_types(self, clickhouse_db):
        assert clickhouse_db.get_supported_search_types() == [SearchType.vector]


class TestWriteStampsOwner:
    """Insert stamps the caller's id into ``user_id``; ``None`` and an omitted arg collapse to ``""``."""

    def test_explicit_user_id_stamped_into_column(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h1", documents=[_doc("alice", "alice content")], user_id="alice")
        assert _owner_of(clickhouse_db.client) == "alice"

    def test_none_user_id_stamped_as_shared_sentinel(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h1", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owner_of(clickhouse_db.client) == SHARED_OWNER

    def test_user_id_omitted_defaults_to_shared(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h1", documents=[_doc("shared", "shared content")])
        assert _owner_of(clickhouse_db.client) == SHARED_OWNER

    def test_column_names_match_row_arity(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h1", documents=[_doc("alice", "x")], user_id="alice")
        row, idx = _insert_row(clickhouse_db.client)
        assert set(idx) == set(INSERT_COLUMNS)
        assert len(row) == len(INSERT_COLUMNS)


class TestOwnerFoldedId:
    """The owner is folded into the row id; the shared (``None``) row keeps the plain content-hash id."""

    def test_two_owners_identical_content_get_distinct_ids(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        alice_id = _id_of(clickhouse_db.client)

        clickhouse_db.client.insert.reset_mock()
        clickhouse_db.insert(content_hash="h", documents=[_doc("bob", "same text")], user_id="bob")
        bob_id = _id_of(clickhouse_db.client)

        assert alice_id != bob_id

    def test_shared_content_keeps_base_id(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h", documents=[_doc("shared", "same text")], user_id=None)
        expected = md5("same text".encode()).hexdigest()
        assert _id_of(clickhouse_db.client) == expected

    def test_owner_folded_id_is_hash_of_base_and_owner(self, clickhouse_db):
        clickhouse_db.insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        base = md5("same text".encode()).hexdigest()
        expected = md5(f"{base}_alice".encode()).hexdigest()
        assert _id_of(clickhouse_db.client) == expected


class TestSearchScope:
    """A scoped search restricts to ``user_id = {bound} OR user_id = ''``, with the owner bound not interpolated."""

    def _search_call(self, client):
        call = client.query.call_args
        return call.args[0], call.kwargs["parameters"]

    def test_scoped_search_where_is_own_or_shared(self, clickhouse_db):
        clickhouse_db.search("salary", limit=10, user_id="alice")
        sql, params = self._search_call(clickhouse_db.client)
        assert "WHERE (user_id = {user_id:String} OR user_id = '')" in sql
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    def test_admin_search_has_no_scope(self, clickhouse_db):
        clickhouse_db.search("salary", limit=10, user_id=None)
        sql, params = self._search_call(clickhouse_db.client)
        assert "WHERE" not in sql
        assert "user_id" not in params

    @pytest.mark.asyncio
    async def test_async_scoped_search_where_is_own_or_shared(self, clickhouse_db):
        await clickhouse_db.async_search("salary", limit=10, user_id="alice")
        sql, params = self._search_call(clickhouse_db.async_client)
        assert "WHERE (user_id = {user_id:String} OR user_id = '')" in sql
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    @pytest.mark.asyncio
    async def test_async_admin_search_has_no_scope(self, clickhouse_db):
        await clickhouse_db.async_search("salary", limit=10, user_id=None)
        sql, params = self._search_call(clickhouse_db.async_client)
        assert "WHERE" not in sql
        assert "user_id" not in params


def _delete_command(client, needle="content_id"):
    """The most recent DELETE command carrying ``needle`` and its parameters."""
    for call in reversed(client.command.call_args_list):
        sql = call.args[0]
        if "DELETE" in sql and needle in sql:
            return sql, call.kwargs["parameters"]
    raise AssertionError(f"no DELETE command matching {needle!r} was issued")


class TestDeleteScope:
    """``delete_by_content_id`` scopes to the caller's rows; ``None`` spans all owners."""

    def test_scoped_delete_ands_owner(self, clickhouse_db):
        clickhouse_db.delete_by_content_id("doc-1", user_id="bob")
        sql, params = _delete_command(clickhouse_db.client)
        assert "WHERE content_id = {content_id:String}" in sql
        assert "AND user_id = {user_id:String}" in sql
        assert params["content_id"] == "doc-1"
        assert params["user_id"] == "bob"
        assert "bob" not in sql

    def test_unscoped_delete_is_content_id_only(self, clickhouse_db):
        clickhouse_db.delete_by_content_id("doc-1", user_id=None)
        sql, params = _delete_command(clickhouse_db.client)
        assert "WHERE content_id = {content_id:String}" in sql
        assert "user_id" not in sql
        assert "user_id" not in params


class TestUpsertDedupScope:
    """``upsert`` dedups within the writing owner's bucket only."""

    def test_scoped_dedup_delete_targets_owner(self, clickhouse_db):
        # Force the dedup path: the owner already has this content_hash.
        clickhouse_db.content_hash_exists = MagicMock(return_value=True)
        clickhouse_db.upsert(content_hash="h", documents=[_doc("alice", "text")], user_id="alice")

        sql, params = _delete_command(clickhouse_db.client, needle="content_hash")
        assert "WHERE content_hash = {content_hash:String} AND user_id = {user_id:String}" in sql
        assert params["content_hash"] == "h"
        assert params["user_id"] == "alice"

    def test_shared_dedup_delete_targets_shared_bucket(self, clickhouse_db):
        clickhouse_db.content_hash_exists = MagicMock(return_value=True)
        clickhouse_db.upsert(content_hash="h", documents=[_doc("shared", "text")], user_id=None)

        sql, params = _delete_command(clickhouse_db.client, needle="content_hash")
        assert "WHERE content_hash = {content_hash:String} AND user_id = {user_id:String}" in sql
        assert params["user_id"] == SHARED_OWNER

    def test_upsert_dedup_check_is_scoped_to_writing_owner(self, clickhouse_db):
        clickhouse_db.content_hash_exists = MagicMock(return_value=False)
        clickhouse_db.upsert(content_hash="h", documents=[_doc("bob", "text")], user_id="bob")
        clickhouse_db.content_hash_exists.assert_called_once_with("h", user_id="bob")

    def test_direct_delete_by_content_hash_binds_owner(self, clickhouse_db):
        clickhouse_db._delete_by_content_hash("h", user_id="alice")
        sql, params = _delete_command(clickhouse_db.client, needle="content_hash")
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    @pytest.mark.asyncio
    async def test_async_shared_dedup_delete_targets_shared_bucket(self, clickhouse_db):
        clickhouse_db.content_hash_exists = MagicMock(return_value=True)
        await clickhouse_db.async_upsert(content_hash="h", documents=[_doc("shared", "text")], user_id=None)
        # async_upsert routes its dedup delete through the sync client.command.
        sql, params = _delete_command(clickhouse_db.client, needle="content_hash")
        assert params["user_id"] == SHARED_OWNER


class TestContentHashExistsScope:
    """The dedup existence check is scoped by owner; ``None`` checks only the shared bucket."""

    def _call(self, client):
        for call in reversed(client.query.call_args_list):
            if "content_hash" in call.args[0]:
                return call.args[0], call.kwargs["parameters"]
        raise AssertionError("no content_hash query was issued")

    def test_scoped_check_binds_owner(self, clickhouse_db):
        clickhouse_db.content_hash_exists("h1", user_id="alice")
        sql, params = self._call(clickhouse_db.client)
        assert "WHERE content_hash = {content_hash:String} AND user_id = {user_id:String}" in sql
        assert params["user_id"] == "alice"

    def test_none_check_binds_shared_bucket(self, clickhouse_db):
        clickhouse_db.content_hash_exists("h1", user_id=None)
        _, params = self._call(clickhouse_db.client)
        assert params["user_id"] == SHARED_OWNER


class TestAsyncIsolation:
    """The async write path stamps the owner exactly like the sync path."""

    @pytest.mark.asyncio
    async def test_async_explicit_user_id_stamped(self, clickhouse_db):
        await clickhouse_db.async_insert(content_hash="h1", documents=[_doc("alice", "alice content")], user_id="alice")
        assert _owner_of(clickhouse_db.async_client) == "alice"

    @pytest.mark.asyncio
    async def test_async_none_user_id_is_shared(self, clickhouse_db):
        await clickhouse_db.async_insert(content_hash="h1", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owner_of(clickhouse_db.async_client) == SHARED_OWNER

    @pytest.mark.asyncio
    async def test_async_two_owners_get_distinct_ids(self, clickhouse_db):
        await clickhouse_db.async_insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        alice_id = _id_of(clickhouse_db.async_client)
        clickhouse_db.async_client.insert.reset_mock()
        await clickhouse_db.async_insert(content_hash="h", documents=[_doc("bob", "same text")], user_id="bob")
        bob_id = _id_of(clickhouse_db.async_client)
        assert alice_id != bob_id


class TestSentinelImpersonation:
    """``""`` is the shared bucket sentinel, so every scoped entry point rejects it."""

    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.insert("h", [_doc("alice", "alice content")], user_id=""),
            lambda db: db.upsert("h", [_doc("alice", "alice content")], user_id=""),
            lambda db: db.search("salary", limit=10, user_id=""),
            lambda db: db.content_hash_exists("h", user_id=""),
            lambda db: db.delete_by_content_id("cid", user_id=""),
            lambda db: db._delete_by_content_hash("h", user_id=""),
        ],
        ids=["insert", "upsert", "search", "content_hash_exists", "delete_by_content_id", "_delete_by_content_hash"],
    )
    def test_every_scoped_entry_point_rejects(self, clickhouse_db, call):
        with pytest.raises(ValueError, match="user_id must not be an empty string"):
            call(clickhouse_db)

        clickhouse_db.client.insert.assert_not_called()
        clickhouse_db.client.command.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "call",
        [
            lambda db: db.async_insert("h", [_doc("alice", "alice content")], user_id=""),
            lambda db: db.async_upsert("h", [_doc("alice", "alice content")], user_id=""),
            lambda db: db.async_search("salary", limit=10, user_id=""),
        ],
        ids=["async_insert", "async_upsert", "async_search"],
    )
    async def test_every_async_entry_point_rejects(self, clickhouse_db, call):
        with pytest.raises(ValueError, match="user_id must not be an empty string"):
            await call(clickhouse_db)

        clickhouse_db.async_client.insert.assert_not_called()

    def test_none_is_not_rejected(self, clickhouse_db):
        """``None`` is the supported way to reach the shared bucket - only the literal sentinel is refused."""
        clickhouse_db.insert(content_hash="h", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owner_of(clickhouse_db.client) == SHARED_OWNER
