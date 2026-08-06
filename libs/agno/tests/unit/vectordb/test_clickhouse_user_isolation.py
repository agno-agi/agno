"""ClickHouse per-user RAG isolation contract.

The owner lives in a dedicated ``user_id`` String column. Inserts stamp the
caller's id (``user_id=None`` -> the shared sentinel ``""``), scoped searches
return the caller's rows plus the shared bucket, and ``user_id=None`` at read
time is the admin view that sees everything.

The clickhouse clients are mocked so no server is touched. We capture the
values the adapter feeds the driver — the ``user_id`` column value on
``client.insert``, and the SQL text + bound ``parameters`` on
``client.command`` / ``client.query`` — and assert on those directly.
"""

from hashlib import md5
from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.knowledge.document import Document
from agno.vectordb.clickhouse import Clickhouse
from agno.vectordb.clickhouse.clickhousedb import SHARED_OWNER
from agno.vectordb.search import SearchType

# The column order the adapter writes; indices are resolved from the captured
# ``column_names`` so a column reorder can't make the assertions read the
# wrong cell.
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


def _content_hash_store(client, rows):
    """Answer ``content_hash`` lookups from ``rows`` — a list of
    ``(content_hash, user_id)`` — applying the owner clause only when the SQL
    the adapter built actually carries it, the way the server would."""

    def query(sql, parameters=None):
        parameters = parameters or {}
        if "content_hash" not in sql:
            return _empty_result()
        matched = [row for row in rows if row[0] == parameters.get("content_hash")]
        if "user_id" in sql:
            matched = [row for row in matched if row[1] == parameters.get("user_id")]
        result = MagicMock()
        result.result_rows = [(row[0],) for row in matched]
        result.first_row = result.result_rows[0] if result.result_rows else None
        return result

    client.query.side_effect = query


@pytest.fixture
def mock_client():
    """Create a mock Clickhouse client."""
    client = MagicMock()
    client.query.return_value = _empty_result()
    return client


@pytest.fixture
def mock_async_client():
    """Create a mock Clickhouse async client."""
    async_client = AsyncMock()
    async_client.command.return_value = None
    async_client.query.return_value = _empty_result()
    return async_client


@pytest.fixture
def clickhouse_db(mock_client, mock_async_client):
    """Create a Clickhouse instance with mocked clients."""
    return Clickhouse(
        table_name="iso_tbl",
        host="localhost",
        database_name="iso_db",
        embedder=_DeterministicEmbedder(),
        client=mock_client,
        asyncclient=mock_async_client,
    )


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

    def test_get_supported_search_types(self, clickhouse_db):
        assert clickhouse_db.get_supported_search_types() == [SearchType.vector]


class TestInsertStampsOwner:
    """On insert the caller's id lands in the ``user_id`` column; ``None`` (and
    an omitted arg) collapse to the shared sentinel ``""``."""

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


class TestIdFolding:
    """The owner is folded into the row id so two owners' copies of identical
    content occupy distinct ids and can't overwrite one another; the shared
    (``None``) row keeps the plain content-hash id."""

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
    """A scoped search restricts to ``user_id = {bound} OR user_id = ''`` with
    the owner passed as a bound parameter (never string-interpolated). Admin
    (``user_id=None``) builds no scope and binds no owner."""

    def _search_call(self, client):
        call = client.query.call_args
        return call.args[0], call.kwargs["parameters"]

    def test_scoped_search_where_is_own_or_shared(self, clickhouse_db):
        clickhouse_db.search("salary", limit=10, user_id="alice")
        sql, params = self._search_call(clickhouse_db.client)
        assert "WHERE (user_id = {user_id:String} OR user_id = '')" in sql
        # Owner is bound, not interpolated into the SQL text.
        assert params["user_id"] == "alice"
        assert "alice" not in sql

    def test_admin_search_has_no_scope(self, clickhouse_db):
        clickhouse_db.search("salary", limit=10, user_id=None)
        sql, params = self._search_call(clickhouse_db.client)
        assert "WHERE" not in sql
        assert "user_id" not in params

    async def test_async_scoped_search_where_is_own_or_shared(self, clickhouse_db):
        await clickhouse_db.async_search("salary", limit=10, user_id="alice")
        sql, params = self._search_call(clickhouse_db.async_client)
        assert "WHERE (user_id = {user_id:String} OR user_id = '')" in sql
        assert params["user_id"] == "alice"
        assert "alice" not in sql

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


class TestDeleteByContentIdScope:
    """``delete_by_content_id`` scopes to the caller's rows; ``None`` spans all
    owners. The owner is bound, never interpolated."""

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
    """``upsert`` dedups within the caller's bucket only: the pre-insert dedup
    delete is scoped to the writing owner, and a shared (``None``) re-ingest
    scopes to the shared bucket ``''`` so it can't evict an owned identical row.
    """

    def test_scoped_dedup_delete_targets_owner(self, clickhouse_db):
        # Force the dedup path: pretend the owner already has this content_hash.
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
        # None scopes the dedup to the shared bucket, never every owner's rows.
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

    async def test_async_shared_dedup_delete_targets_shared_bucket(self, clickhouse_db):
        clickhouse_db.content_hash_exists = MagicMock(return_value=True)
        await clickhouse_db.async_upsert(content_hash="h", documents=[_doc("shared", "text")], user_id=None)
        # async_upsert routes its dedup delete through the sync client.command.
        sql, params = _delete_command(clickhouse_db.client, needle="content_hash")
        assert params["user_id"] == SHARED_OWNER


class TestContentHashExistsScope:
    """The dedup existence check keys on ``content_hash`` scoped by owner. It is
    the guard half of the upsert dedup pair, so it means what
    ``_delete_by_content_hash`` means: ``None`` checks only the shared bucket,
    never every owner's rows."""

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

    def test_none_check_sees_the_shared_row(self, clickhouse_db):
        _content_hash_store(clickhouse_db.client, [("h1", SHARED_OWNER)])
        assert clickhouse_db.content_hash_exists("h1", user_id=None) is True

    def test_none_check_does_not_see_a_privately_owned_row(self, clickhouse_db):
        """Alice privately holds this content. If ``None`` matched her row, a shared
        publish of the same bytes would be judged a duplicate and silently skipped,
        and the shared bucket would never receive it."""
        _content_hash_store(clickhouse_db.client, [("h1", "alice")])
        assert clickhouse_db.content_hash_exists("h1", user_id=None) is False
        assert clickhouse_db.content_hash_exists("h1", user_id="alice") is True


class TestAsyncInsertStampsOwner:
    """The async write path stamps the owner exactly like the sync path."""

    async def test_async_explicit_user_id_stamped(self, clickhouse_db):
        await clickhouse_db.async_insert(content_hash="h1", documents=[_doc("alice", "alice content")], user_id="alice")
        assert _owner_of(clickhouse_db.async_client) == "alice"

    async def test_async_none_user_id_is_shared(self, clickhouse_db):
        await clickhouse_db.async_insert(content_hash="h1", documents=[_doc("shared", "shared content")], user_id=None)
        assert _owner_of(clickhouse_db.async_client) == SHARED_OWNER

    async def test_async_two_owners_get_distinct_ids(self, clickhouse_db):
        await clickhouse_db.async_insert(content_hash="h", documents=[_doc("alice", "same text")], user_id="alice")
        alice_id = _id_of(clickhouse_db.async_client)
        clickhouse_db.async_client.insert.reset_mock()
        await clickhouse_db.async_insert(content_hash="h", documents=[_doc("bob", "same text")], user_id="bob")
        bob_id = _id_of(clickhouse_db.async_client)
        assert alice_id != bob_id
