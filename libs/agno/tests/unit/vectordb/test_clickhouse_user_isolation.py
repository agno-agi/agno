"""ClickHouse per-user RAG isolation contract.

The owner lives in a dedicated ``user_id`` String column. Inserts stamp the
caller's id (``user_id=None`` -> the shared sentinel ``""``), scoped searches
return the caller's rows plus the shared bucket, and ``user_id=None`` at read
time is the admin view that sees everything.

This is a TRUE unit test: ``clickhouse_connect`` is patched so no server is
touched. We capture the exact values the adapter feeds the driver — the
``user_id`` column value on ``client.insert``, and the SQL text + bound
``parameters`` on ``client.command`` / ``client.query`` — and assert the
isolation-determining values directly. If the scope predicate, the owner
column, or the id folding regresses, these assertions fail.
"""

from hashlib import md5
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Library dependency check only — this test never connects to a server.
clickhouse_connect = pytest.importorskip("clickhouse_connect")

from agno.knowledge.document import Document  # noqa: E402
from agno.vectordb.clickhouse import Clickhouse  # noqa: E402
from agno.vectordb.clickhouse.clickhousedb import SHARED_OWNER  # noqa: E402
from agno.vectordb.search import SearchType  # noqa: E402

# The column order the adapter writes; we resolve indices from the captured
# ``column_names`` rather than hard-coding, so a column reorder can't silently
# make the owner assertions read the wrong cell.
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


class _DeterministicEmbedder:
    """A tiny embedder that needs no network or API key."""

    dimensions = 8
    enable_batch = False

    def get_embedding(self, text):
        vector = [0.0] * self.dimensions
        vector[abs(hash(text)) % self.dimensions] = 1.0
        return vector

    def get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    async def async_get_embedding(self, text):
        return self.get_embedding(text)

    async def async_get_embedding_and_usage(self, text):
        return self.get_embedding(text), {"total_tokens": 1}

    def embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}

    async def async_embed(self, document, *args, **kwargs):
        document.embedding = self.get_embedding(document.content)
        document.usage = {"total_tokens": 1}


def _doc(name: str, content: str, content_id: str = None) -> Document:
    doc = Document(name=name, content=content)
    doc.content_id = content_id if content_id is not None else name
    doc.embedding = _DeterministicEmbedder().get_embedding(content)
    return doc


def _empty_result():
    """A query result the search/exists paths can iterate without a server."""
    result = MagicMock()
    result.result_rows = []
    result.first_row = None
    return result


@pytest.fixture
def ch_db():
    """A Clickhouse adapter wired to a mocked ``clickhouse_connect`` — no server.

    ``get_client`` returns a sync MagicMock client and ``get_async_client``
    (awaited by the adapter) an AsyncMock-backed async client. All three call
    surfaces we assert on — ``insert``, ``command``, ``query`` — are captured.
    """
    with patch("agno.vectordb.clickhouse.clickhousedb.clickhouse_connect") as mock_cc:
        sync_client = MagicMock()
        sync_client.query.return_value = _empty_result()
        mock_cc.get_client.return_value = sync_client

        async_client = MagicMock()
        async_client.insert = AsyncMock()
        async_client.command = AsyncMock()
        async_client.query = AsyncMock(return_value=_empty_result())
        mock_cc.get_async_client = AsyncMock(return_value=async_client)

        db = Clickhouse(
            table_name="iso_tbl",
            host="localhost",
            database_name="iso_db",
            embedder=_DeterministicEmbedder(),
        )
        # Expose the async client for assertions without re-awaiting.
        db._captured_async_client = async_client
        yield db


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
    """Pin the sentinel and the supported search type."""

    def test_shared_owner_sentinel_is_empty_string(self):
        assert SHARED_OWNER == ""

    def test_get_supported_search_types(self, ch_db):
        assert ch_db.get_supported_search_types() == [SearchType.vector]


class TestInsertStampsOwner:
    """On insert the caller's id lands in the ``user_id`` column; ``None`` (and
    an omitted arg) collapse to the shared sentinel ``""``."""

    def test_explicit_user_id_stamped_into_column(self, ch_db):
        ch_db.insert(content_hash="h1", documents=[_doc("alice", "alice content")], user_id="alice")
        assert _owner_of(ch_db.client) == "alice"

    def test_none_user_id_stamped_as_shared_sentinel(self, ch_db):
        ch_db.insert(content_hash="h1", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owner_of(ch_db.client) == SHARED_OWNER

    def test_user_id_omitted_defaults_to_shared(self, ch_db):
        ch_db.insert(content_hash="h1", documents=[_doc("shared", "shared content")])
        assert _owner_of(ch_db.client) == SHARED_OWNER

    def test_column_names_match_row_arity(self, ch_db):
        ch_db.insert(content_hash="h1", documents=[_doc("alice", "x")], user_id="alice")
        row, idx = _insert_row(ch_db.client)
        assert set(idx) == set(INSERT_COLUMNS)
        assert len(row) == len(INSERT_COLUMNS)


class TestIdFolding:
    """The owner is folded into the row id so two owners' copies of identical
    content occupy distinct ids and can't overwrite one another; the shared
    (``None``) row keeps the plain content-hash id."""

    def test_two_owners_identical_content_get_distinct_ids(self, ch_db):
        ch_db.insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        alice_id = _id_of(ch_db.client)

        ch_db.client.insert.reset_mock()
        ch_db.insert(content_hash="h", documents=[_doc("bob", "same text")], user_id="bob")
        bob_id = _id_of(ch_db.client)

        assert alice_id != bob_id

    def test_shared_content_keeps_base_id(self, ch_db):
        ch_db.insert(content_hash="h", documents=[_doc("shared", "same text")], user_id=None)
        expected = md5("same text".encode()).hexdigest()
        assert _id_of(ch_db.client) == expected

    def test_owner_folded_id_is_hash_of_base_and_owner(self, ch_db):
        ch_db.insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        base = md5("same text".encode()).hexdigest()
        expected = md5(f"{base}_alice".encode()).hexdigest()
        assert _id_of(ch_db.client) == expected


class TestSearchScope:
    """A scoped search restricts to ``user_id = {bound} OR user_id = ''`` with
    the owner passed as a bound parameter (never string-interpolated). Admin
    (``user_id=None``) builds no scope and binds no owner."""

    def _search_call(self, client):
        call = client.query.call_args
        return call.args[0], call.kwargs["parameters"]

    def test_scoped_search_where_is_own_or_shared(self, ch_db):
        ch_db.search("salary", limit=10, user_id="alice")
        sql, params = self._search_call(ch_db.client)
        assert "WHERE (user_id = {user_id:String} OR user_id = '')" in sql
        # Owner is bound, not interpolated into the SQL text.
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    def test_admin_search_has_no_scope(self, ch_db):
        ch_db.search("salary", limit=10, user_id=None)
        sql, params = self._search_call(ch_db.client)
        assert "WHERE" not in sql
        assert "user_id" not in params

    async def test_async_scoped_search_where_is_own_or_shared(self, ch_db):
        await ch_db.async_search("salary", limit=10, user_id="alice")
        sql, params = self._search_call(ch_db._captured_async_client)
        assert "WHERE (user_id = {user_id:String} OR user_id = '')" in sql
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    async def test_async_admin_search_has_no_scope(self, ch_db):
        await ch_db.async_search("salary", limit=10, user_id=None)
        sql, params = self._search_call(ch_db._captured_async_client)
        assert "WHERE" not in sql
        assert "user_id" not in params


def _delete_command(client, needle="content_id"):
    """The most recent DELETE command carrying ``needle`` and its parameters."""
    for call in reversed(client.command.call_args_list):
        sql = call.args[0]
        if "DELETE" in sql and needle in sql:
            return sql, call.kwargs["parameters"]
    raise AssertionError(f"no DELETE command matching {needle!r} was issued")


class TestDeleteByContentIdScope:
    """``delete_by_content_id`` scopes to the caller's rows; ``None`` spans all
    owners. The owner is bound, never interpolated."""

    def test_scoped_delete_ands_owner(self, ch_db):
        ch_db.delete_by_content_id("doc-1", user_id="bob")
        sql, params = _delete_command(ch_db.client)
        assert "WHERE content_id = {content_id:String}" in sql
        assert "AND user_id = {user_id:String}" in sql
        assert params["content_id"] == "doc-1"
        assert params["user_id"] == "bob"
        assert "bob" not in sql

    def test_unscoped_delete_is_content_id_only(self, ch_db):
        ch_db.delete_by_content_id("doc-1", user_id=None)
        sql, params = _delete_command(ch_db.client)
        assert "WHERE content_id = {content_id:String}" in sql
        assert "user_id" not in sql
        assert "user_id" not in params


class TestUpsertDedupScope:
    """``upsert`` dedups within the caller's bucket only: the pre-insert dedup
    delete is scoped to the writing owner, and a shared (``None``) re-ingest
    scopes to the shared bucket ``''`` so it can't evict an owned identical row.
    """

    def test_scoped_dedup_delete_targets_owner(self, ch_db):
        # Force the dedup path: pretend the owner already has this content_hash.
        ch_db.content_hash_exists = MagicMock(return_value=True)
        ch_db.upsert(content_hash="h", documents=[_doc("alice", "text")], user_id="alice")

        sql, params = _delete_command(ch_db.client, needle="content_hash")
        assert "WHERE content_hash = {content_hash:String} AND user_id = {user_id:String}" in sql
        assert params["content_hash"] == "h"
        assert params["user_id"] == "alice"

    def test_shared_dedup_delete_targets_shared_bucket(self, ch_db):
        ch_db.content_hash_exists = MagicMock(return_value=True)
        ch_db.upsert(content_hash="h", documents=[_doc("shared", "text")], user_id=None)

        sql, params = _delete_command(ch_db.client, needle="content_hash")
        assert "WHERE content_hash = {content_hash:String} AND user_id = {user_id:String}" in sql
        # None scopes the dedup to the shared bucket, never every owner's rows.
        assert params["user_id"] == SHARED_OWNER

    def test_upsert_dedup_check_is_scoped_to_writing_owner(self, ch_db):
        ch_db.content_hash_exists = MagicMock(return_value=False)
        ch_db.upsert(content_hash="h", documents=[_doc("bob", "text")], user_id="bob")
        ch_db.content_hash_exists.assert_called_once_with("h", user_id="bob")

    def test_direct_delete_by_content_hash_binds_owner(self, ch_db):
        """The scoped dedup primitive binds the owner rather than interpolating."""
        ch_db._delete_by_content_hash("h", user_id="alice")
        sql, params = _delete_command(ch_db.client, needle="content_hash")
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    async def test_async_shared_dedup_delete_targets_shared_bucket(self, ch_db):
        ch_db.content_hash_exists = MagicMock(return_value=True)
        await ch_db.async_upsert(content_hash="h", documents=[_doc("shared", "text")], user_id=None)
        # async_upsert routes its dedup delete through the sync client.command.
        sql, params = _delete_command(ch_db.client, needle="content_hash")
        assert params["user_id"] == SHARED_OWNER


class TestContentHashExistsScope:
    """The dedup existence check keys on ``content_hash`` scoped by owner;
    ``None`` checks only the shared bucket, never every owner's rows."""

    def test_scoped_check_binds_owner(self, ch_db):
        ch_db.content_hash_exists("h1", user_id="alice")
        sql, params = self._call(ch_db.client)
        assert "WHERE content_hash = {content_hash:String} AND user_id = {user_id:String}" in sql
        assert params["user_id"] == "alice"

    def test_none_check_binds_shared_bucket(self, ch_db):
        ch_db.content_hash_exists("h1", user_id=None)
        _, params = self._call(ch_db.client)
        assert params["user_id"] == SHARED_OWNER

    def _call(self, client):
        for call in reversed(client.query.call_args_list):
            if "content_hash" in call.args[0]:
                return call.args[0], call.kwargs["parameters"]
        raise AssertionError("no content_hash query was issued")


class TestAsyncInsertStampsOwner:
    """The async write path stamps the owner exactly like the sync path."""

    async def test_async_explicit_user_id_stamped(self, ch_db):
        await ch_db.async_insert(content_hash="h1", documents=[_doc("alice", "alice content")], user_id="alice")
        assert _owner_of(ch_db._captured_async_client) == "alice"

    async def test_async_none_user_id_is_shared(self, ch_db):
        await ch_db.async_insert(content_hash="h1", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owner_of(ch_db._captured_async_client) == SHARED_OWNER

    async def test_async_two_owners_get_distinct_ids(self, ch_db):
        await ch_db.async_insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        alice_id = _id_of(ch_db._captured_async_client)
        ch_db._captured_async_client.insert.reset_mock()
        await ch_db.async_insert(content_hash="h", documents=[_doc("bob", "same text")], user_id="bob")
        bob_id = _id_of(ch_db._captured_async_client)
        assert alice_id != bob_id
