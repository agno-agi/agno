"""SurrealDB per-user RAG isolation contract, against in-memory fakes that record queries and creates."""

import uuid

import pytest

from agno.knowledge.document import Document
from agno.vectordb.surrealdb import SurrealDb

from .conftest import DeterministicEmbedder

# A shared row carries ``None`` in the record body (persisted as NONE/NULL).
SHARED_MARKER = None


class FakeSurreal:
    """A fake blocking SurrealDB connection that records every call."""

    def __init__(self):
        self.queries = []
        self.creates = []
        self.query_return = []

    def query(self, sql, vars=None):
        self.queries.append((sql, vars))
        return self.query_return

    def create(self, table, data):
        self.creates.append((table, data))
        return data


class FakeAsyncSurreal:
    """Async twin of ``FakeSurreal``."""

    def __init__(self):
        self.queries = []
        self.creates = []
        self.query_return = []

    async def query(self, sql, vars=None):
        self.queries.append((sql, vars))
        return self.query_return

    async def create(self, table, data):
        self.creates.append((table, data))
        return data


COLLECTION = "iso_" + uuid.uuid4().hex[:10]


@pytest.fixture
def surreal_db():
    """Fixture to create a SurrealDb backed by the fake blocking client"""
    return SurrealDb(client=FakeSurreal(), collection=COLLECTION, embedder=DeterministicEmbedder())


@pytest.fixture
def async_surreal_db():
    """Fixture to create a SurrealDb backed by the fake async client"""
    return SurrealDb(async_client=FakeAsyncSurreal(), collection=COLLECTION, embedder=DeterministicEmbedder())


def _doc(content: str) -> Document:
    return Document(content=content)


def _doc_with_id(content: str, doc_id: str) -> Document:
    """A document with a reader-assigned id, as Knowledge hands the backend on upsert."""
    doc = Document(content=content)
    doc.id = doc_id
    return doc


def _last_create_body(client) -> dict:
    """The record body of the most recent ``client.create`` call."""
    assert client.creates, "expected a client.create() call"
    return client.creates[-1][1]


def _last_query(client):
    """The (sql, bound_vars) of the most recent ``client.query`` call."""
    assert client.queries, "expected a client.query() call"
    return client.queries[-1]


def _query_matching(client, needle: str):
    """The (sql, bound_vars) of the most recent query containing ``needle``."""
    for sql, params in reversed(client.queries):
        if needle in sql:
            return sql, params
    raise AssertionError(f"no query containing {needle!r} was issued")


def _delete_by_hash_query(client):
    return _query_matching(client, "DELETE FROM")


def _content_hash_query(client):
    return _query_matching(client, "SELECT")


class TestWriteStampsOwner:
    """The written record carries the owner as a top-level ``user_id``, not nested in meta_data."""

    def test_explicit_user_id_stored_top_level_on_insert(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("alice content")], user_id="alice")
        body = _last_create_body(surreal_db.client)
        assert body["user_id"] == "alice"
        assert body["meta_data"].get("user_id") is None

    def test_explicit_user_id_stored_top_level_on_upsert(self, surreal_db):
        surreal_db.upsert(
            content_hash="h1", documents=[_doc_with_id("alice content", str(uuid.uuid4()))], user_id="alice"
        )
        _sql, body = _last_query(surreal_db.client)
        assert body["user_id"] == "alice"
        assert body["meta_data"].get("user_id") is None

    def test_none_user_id_stored_as_shared_marker(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")], user_id=None)
        assert _last_create_body(surreal_db.client)["user_id"] is SHARED_MARKER

    def test_omitted_user_id_defaults_to_shared(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")])
        assert _last_create_body(surreal_db.client)["user_id"] is SHARED_MARKER

    def test_caller_metadata_cannot_spoof_owner(self, surreal_db):
        """``user_id`` in a document's meta_data must not override the owner stamped from the param."""
        doc = Document(content="c")
        doc.meta_data = {"user_id": "attacker"}
        surreal_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        assert _last_create_body(surreal_db.client)["user_id"] == "alice"


class TestOwnerFoldedId:
    """The owner is folded into the record id; the shared bucket keeps the base id."""

    def test_two_owners_same_id_get_distinct_record_ids(self, surreal_db):
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="alice")
        _sql_a, alice_body = _last_query(surreal_db.client)
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="bob")
        _sql_b, bob_body = _last_query(surreal_db.client)

        assert alice_body["record_id"] == f"{shared_id}:alice"
        assert bob_body["record_id"] == f"{shared_id}:bob"
        # Distinct ids mean bob's UPSERT can never overwrite alice's identical-content row.
        assert alice_body["record_id"] != bob_body["record_id"]

    def test_shared_upsert_keeps_base_id(self, surreal_db):
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id=None)
        _sql, body = _last_query(surreal_db.client)
        assert body["record_id"] == shared_id

    def test_shared_id_is_escaped_by_the_same_rule_as_a_fold(self):
        """':' is the fold delimiter and a legal id character, so a shared id carrying one must be escaped."""
        assert SurrealDb._fold_record_id("http://x", None) == "http%3A//x"
        assert SurrealDb._fold_record_id("http://x", None) != SurrealDb._fold_record_id("http", "//x")
        # A percent in the id cannot forge an escape sequence either.
        assert SurrealDb._fold_record_id("a%3Ab", None) != SurrealDb._fold_record_id("a:b", None)

    def test_shared_and_owned_ids_do_not_collide(self, surreal_db):
        """A shared re-ingest (base id) and an owner (``id:owner``) land on distinct records."""
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="alice")
        _sql_a, alice_body = _last_query(surreal_db.client)
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id=None)
        _sql_s, shared_body = _last_query(surreal_db.client)
        assert alice_body["record_id"] == f"{shared_id}:alice"
        assert shared_body["record_id"] == shared_id
        assert alice_body["record_id"] != shared_body["record_id"]


class TestSearchScope:
    """A scoped search matches the caller's own rows or the shared (NONE) bucket, and nothing else."""

    OWN_OR_SHARED = "AND (user_id = $scope_user_id OR user_id = NONE)"

    def test_scoped_search_restricts_to_own_or_shared(self, surreal_db):
        surreal_db.search("salary", limit=10, user_id="alice")
        sql, params = _last_query(surreal_db.client)
        assert self.OWN_OR_SHARED in sql
        assert params["scope_user_id"] == "alice"
        # Owner bound as a variable, never spliced into the SQL text.
        assert "alice" not in sql

    def test_admin_search_has_no_scope(self, surreal_db):
        surreal_db.search("salary", limit=10, user_id=None)
        sql, params = _last_query(surreal_db.client)
        assert "$scope_user_id" not in sql
        assert "scope_user_id" not in params

    def test_scoped_search_ands_scope_onto_caller_filter(self, surreal_db):
        surreal_db.search("salary", limit=10, filters={"topic": "hr"}, user_id="alice")
        sql, params = _last_query(surreal_db.client)
        # Both the caller's metadata filter and the owner scope apply, with the key bound rather than spliced.
        assert "meta_data[$filter_key_0] = $filter_value_0" in sql
        assert self.OWN_OR_SHARED in sql
        assert params["scope_user_id"] == "alice"
        assert params["filter_key_0"] == "topic"
        assert params["filter_value_0"] == "hr"
        assert "topic" not in sql

    def test_scope_condition_helper_matches(self):
        # Guards the exact predicate the two search methods share.
        assert SurrealDb._user_scope_condition("alice") == self.OWN_OR_SHARED
        assert SurrealDb._user_scope_condition(None) == ""


class TestUpsertDedupScope:
    """An upsert clears the writing owner's chunks for the hash, then rewrites its own folded record."""

    def test_owner_upsert_targets_only_own_record(self, surreal_db):
        shared_id = str(uuid.uuid4())
        # Bob re-ingests content whose id alice also used.
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="bob")
        _sql, bob_body = _last_query(surreal_db.client)
        assert bob_body["record_id"] == f"{shared_id}:bob"
        assert bob_body["record_id"] != f"{shared_id}:alice"
        assert bob_body["record_id"] != shared_id

    def test_upsert_binds_record_id_as_param(self, surreal_db):
        # The id is a bound variable, so the dedup key is never string-built into SQL.
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("c", shared_id)], user_id="alice")
        sql, body = _last_query(surreal_db.client)
        assert "type::record($table, $record_id)" in sql
        assert body["table"] == COLLECTION
        assert body["record_id"] == f"{shared_id}:alice"

    def test_dedup_delete_binds_the_writing_owner(self, surreal_db):
        """The delete only runs when the hash already exists, so the fake has to answer truthy."""
        surreal_db.client.query_return = [{"id": "x"}]
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("c", str(uuid.uuid4()))], user_id="alice")

        sql, params = _delete_by_hash_query(surreal_db.client)
        assert "AND user_id = $user_id" in sql
        assert params["user_id"] == "alice", "a scoped re-upsert must clear only the writing owner's chunks"
        assert params["content_hash"] == "h"

    def test_shared_dedup_delete_targets_the_shared_bucket(self, surreal_db):
        surreal_db.client.query_return = [{"id": "x"}]
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("c", str(uuid.uuid4()))], user_id=None)

        _sql, params = _delete_by_hash_query(surreal_db.client)
        assert params["user_id"] is None, "a shared re-upsert must not reach into an owned bucket"

    def test_guard_and_delete_address_the_same_bucket(self, surreal_db):
        """A guard and delete on different owners either skip a real publish or clear another owner's chunks."""
        surreal_db.client.query_return = [{"id": "x"}]
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("c", str(uuid.uuid4()))], user_id="alice")

        _guard_sql, guard_params = _content_hash_query(surreal_db.client)
        _del_sql, del_params = _delete_by_hash_query(surreal_db.client)
        assert guard_params["user_id"] == del_params["user_id"]

    @pytest.mark.asyncio
    async def test_async_dedup_delete_runs_on_the_async_client(self, async_surreal_db):
        """The blocking and async connections are separate arguments, so both queries must use the async one."""
        async_surreal_db.async_client.query_return = [{"id": "x"}]
        await async_surreal_db.async_upsert(
            content_hash="h", documents=[_doc_with_id("c", str(uuid.uuid4()))], user_id="alice"
        )

        _guard_sql, guard_params = _content_hash_query(async_surreal_db.async_client)
        _del_sql, del_params = _delete_by_hash_query(async_surreal_db.async_client)
        assert guard_params["user_id"] == "alice", "another owner's identical upload must not read as a duplicate"
        assert del_params["user_id"] == "alice"


class TestDeleteScope:
    """A scoped ``delete_by_content_id`` clears only the caller's own chunks."""

    def test_scoped_delete_binds_owner(self, surreal_db):
        surreal_db.delete_by_content_id("doc-1", user_id="bob")
        sql, params = _last_query(surreal_db.client)
        assert "content_id = $content_id" in sql
        assert "AND user_id = $scope_user_id" in sql
        assert params == {"content_id": "doc-1", "scope_user_id": "bob"}

    def test_unscoped_delete_is_content_id_only(self, surreal_db):
        surreal_db.delete_by_content_id("doc-1", user_id=None)
        sql, params = _last_query(surreal_db.client)
        assert "content_id = $content_id" in sql
        assert "user_id" not in sql
        assert params == {"content_id": "doc-1"}


class TestKeyInjectionSafety:
    """A quote/keyword-laden ``user_id`` is bound as a variable, so it lands verbatim and cannot widen the scope."""

    EVIL = "alice' OR user_id = NONE OR '1'='1"

    def test_insert_owner_is_verbatim_literal(self, surreal_db):
        surreal_db.insert(content_hash="h1", documents=[_doc("alice content")], user_id=self.EVIL)
        assert _last_create_body(surreal_db.client)["user_id"] == self.EVIL

    def test_search_scope_binds_not_interpolates(self, surreal_db):
        surreal_db.search("content", limit=10, user_id=self.EVIL)
        sql, params = _last_query(surreal_db.client)
        assert self.EVIL not in sql  # would appear if interpolated
        assert params["scope_user_id"] == self.EVIL
        assert "$scope_user_id" in sql

    def test_delete_scope_binds_not_interpolates(self, surreal_db):
        surreal_db.delete_by_content_id("doc-1", user_id=self.EVIL)
        sql, params = _last_query(surreal_db.client)
        assert self.EVIL not in sql
        assert params["scope_user_id"] == self.EVIL
        assert "$scope_user_id" in sql

    def test_upsert_record_id_binds_not_interpolates(self, surreal_db):
        surreal_db.upsert(content_hash="h1", documents=[_doc_with_id("c", str(uuid.uuid4()))], user_id=self.EVIL)
        sql, body = _last_query(surreal_db.client)
        assert self.EVIL not in sql
        assert body["user_id"] == self.EVIL
        assert body["record_id"].endswith(f":{self.EVIL}")


class TestAsyncIsolation:
    """The isolation contract must hold identically on the async surface."""

    @pytest.mark.asyncio
    async def test_async_insert_stamps_owner(self, async_surreal_db):
        await async_surreal_db.async_insert(content_hash="ha", documents=[_doc("Alice salary")], user_id="alice")
        assert async_surreal_db.async_client.creates[-1][1]["user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_async_insert_none_is_shared(self, async_surreal_db):
        await async_surreal_db.async_insert(content_hash="hs", documents=[_doc("Office closed")], user_id=None)
        assert async_surreal_db.async_client.creates[-1][1]["user_id"] is SHARED_MARKER

    @pytest.mark.asyncio
    async def test_async_search_scopes_to_own_or_shared(self, async_surreal_db):
        await async_surreal_db.async_search("salary", limit=10, user_id="alice")
        sql, params = async_surreal_db.async_client.queries[-1]
        assert "AND (user_id = $scope_user_id OR user_id = NONE)" in sql
        assert params["scope_user_id"] == "alice"
        assert "alice" not in sql

    @pytest.mark.asyncio
    async def test_async_admin_search_has_no_scope(self, async_surreal_db):
        await async_surreal_db.async_search("salary", limit=10, user_id=None)
        sql, params = async_surreal_db.async_client.queries[-1]
        assert "$scope_user_id" not in sql
        assert "scope_user_id" not in params

    @pytest.mark.asyncio
    async def test_async_upsert_two_owners_distinct_record_ids(self, async_surreal_db):
        shared_id = str(uuid.uuid4())
        await async_surreal_db.async_upsert(
            content_hash="h", documents=[_doc_with_id("Same", shared_id)], user_id="alice"
        )
        alice_rid = async_surreal_db.async_client.queries[-1][1]["record_id"]
        await async_surreal_db.async_upsert(
            content_hash="h", documents=[_doc_with_id("Same", shared_id)], user_id="bob"
        )
        bob_rid = async_surreal_db.async_client.queries[-1][1]["record_id"]
        assert alice_rid == f"{shared_id}:alice"
        assert bob_rid == f"{shared_id}:bob"
        assert alice_rid != bob_rid


class TestFilterKeyCannotEscapeTheOwnerScope:
    """A caller's filter key must never reach the query text.

    SurrealQL's ``OR`` binds looser than ``AND``, so an interpolated key carrying ``OR true`` disjoins the owner
    scope away, and one containing '.' splits into an unbound variable that compares equal on every row.
    """

    INJECTION_KEYS = [
        "name OR true",
        "name OR user_id",
        "name OR user_id != NONE",
        "a.b",
    ]

    @pytest.mark.parametrize("evil_key", INJECTION_KEYS)
    def test_injected_key_never_reaches_sql(self, surreal_db, evil_key):
        surreal_db.search("salary", limit=10, filters={evil_key: "x"}, user_id="alice")
        sql, params = _last_query(surreal_db.client)
        assert evil_key not in sql, f"filter key {evil_key!r} was spliced into the query text"
        assert "OR true" not in sql
        assert params["filter_key_0"] == evil_key
        # The owner scope survives intact alongside the bound filter.
        assert TestSearchScope.OWN_OR_SHARED in sql
        assert params["scope_user_id"] == "alice"

    @pytest.mark.parametrize("evil_key", INJECTION_KEYS)
    @pytest.mark.asyncio
    async def test_injected_key_never_reaches_sql_async(self, async_surreal_db, evil_key):
        await async_surreal_db.async_search("salary", limit=10, filters={evil_key: "x"}, user_id="alice")
        sql, params = _last_query(async_surreal_db.async_client)
        assert evil_key not in sql
        assert "OR true" not in sql
        assert params["filter_key_0"] == evil_key
        assert TestSearchScope.OWN_OR_SHARED in sql
        assert params["scope_user_id"] == "alice"

    def test_multiple_filters_each_bound_separately(self, surreal_db):
        surreal_db.search("q", limit=5, filters={"topic": "hr", "year": 2026}, user_id="alice")
        sql, params = _last_query(surreal_db.client)
        assert "meta_data[$filter_key_0] = $filter_value_0" in sql
        assert "meta_data[$filter_key_1] = $filter_value_1" in sql
        assert {params["filter_key_0"], params["filter_key_1"]} == {"topic", "year"}
        assert {params["filter_value_0"], params["filter_value_1"]} == {"hr", 2026}

    def test_condition_and_params_stay_in_step(self):
        """The builders are a pair - every placeholder must have a bound value."""
        filters = {"a": 1, "b OR true": 2}
        condition = SurrealDb._build_filter_condition(filters)
        params = SurrealDb._build_filter_params(filters)
        for i in range(len(filters)):
            assert f"$filter_key_{i}" in condition
            assert f"$filter_value_{i}" in condition
            assert f"filter_key_{i}" in params
            assert f"filter_value_{i}" in params
        assert SurrealDb._build_filter_condition(None) == ""
        assert SurrealDb._build_filter_params(None) == {}
