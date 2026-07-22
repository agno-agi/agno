"""SurrealDB per-user RAG isolation contract.

Inserts stamp ``user_id`` as a first-class field (NONE/NULL == the SHARED
bucket). Scoped searches return the caller's own chunks OR shared chunks, but
never another owner's; unscoped (``user_id=None``) searches are the admin view.
The upsert path folds the owner into the bound record id so two owners'
identical content lands on distinct records.

The adapter takes its client via dependency injection (``client=`` /
``async_client=``), so we inject a fake connection that captures every
``query``/``create`` call — the SQL text, the bound variables, and the written
record body — and assert on those captured values. No server is contacted.
"""

import uuid

import pytest

from agno.knowledge.document import Document
from agno.vectordb.surrealdb import SurrealDb

# A shared row carries ``None`` in the record body (persisted as NONE/NULL).
SHARED_MARKER = None


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

    def embed(self, *args, **kwargs):
        pass

    async def async_embed(self, *args, **kwargs):
        pass


class FakeSurreal:
    """A fake blocking SurrealDB connection that records every call. ``queries``
    holds (sql, bound_vars) tuples; ``creates`` holds (table, record_body)."""

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
def fake_client():
    return FakeSurreal()


@pytest.fixture
def surreal_db(fake_client):
    """A SurrealDb wired to the fake blocking client — no real connection."""
    return SurrealDb(client=fake_client, collection=COLLECTION, embedder=_DeterministicEmbedder())


@pytest.fixture
def fake_async_client():
    return FakeAsyncSurreal()


@pytest.fixture
def async_surreal_db(fake_async_client):
    """A SurrealDb wired to the fake async client — no real connection."""
    return SurrealDb(async_client=fake_async_client, collection=COLLECTION, embedder=_DeterministicEmbedder())


def _doc(content: str) -> Document:
    return Document(content=content)


def _doc_with_id(content: str, doc_id: str) -> Document:
    """A document carrying a reader-assigned UUID id, as Knowledge hands the
    backend on the upsert path."""
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


class TestUserIdStoredAsField:
    """``user_id`` is a first-class field of the written record, not nested in
    meta_data; None/omitted persist as the shared (NONE) bucket."""

    def test_explicit_user_id_stored_top_level_on_insert(self, surreal_db, fake_client):
        surreal_db.insert(content_hash="h1", documents=[_doc("alice content")], user_id="alice")
        body = _last_create_body(fake_client)
        assert body["user_id"] == "alice"
        # Not smuggled into the caller-controlled metadata blob.
        assert body["meta_data"].get("user_id") is None

    def test_explicit_user_id_stored_top_level_on_upsert(self, surreal_db, fake_client):
        surreal_db.upsert(
            content_hash="h1", documents=[_doc_with_id("alice content", str(uuid.uuid4()))], user_id="alice"
        )
        _sql, body = _last_query(fake_client)
        assert body["user_id"] == "alice"
        assert body["meta_data"].get("user_id") is None

    def test_none_user_id_stored_as_shared_marker(self, surreal_db, fake_client):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")], user_id=None)
        assert _last_create_body(fake_client)["user_id"] is SHARED_MARKER

    def test_omitted_user_id_defaults_to_shared(self, surreal_db, fake_client):
        surreal_db.insert(content_hash="h1", documents=[_doc("shared content")])
        assert _last_create_body(fake_client)["user_id"] is SHARED_MARKER

    def test_caller_metadata_cannot_spoof_owner(self, surreal_db, fake_client):
        """A caller stuffing ``user_id`` into a document's meta_data must not
        override the top-level owner the adapter stamps from the param."""
        doc = Document(content="c")
        doc.meta_data = {"user_id": "attacker"}
        surreal_db.insert(content_hash="h1", documents=[doc], user_id="alice")
        assert _last_create_body(fake_client)["user_id"] == "alice"


class TestIdFolding:
    """The owner is folded into the bound record id so two owners' identical
    content lands on DISTINCT records; the shared bucket keeps the base id."""

    def test_two_owners_same_id_get_distinct_record_ids(self, surreal_db, fake_client):
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="alice")
        _sql_a, alice_body = _last_query(fake_client)
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="bob")
        _sql_b, bob_body = _last_query(fake_client)

        assert alice_body["record_id"] == f"{shared_id}:alice"
        assert bob_body["record_id"] == f"{shared_id}:bob"
        # Distinct record ids => bob's UPSERT targets a different record and can
        # never overwrite (steal) alice's identical-content row.
        assert alice_body["record_id"] != bob_body["record_id"]

    def test_shared_upsert_keeps_base_id(self, surreal_db, fake_client):
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id=None)
        _sql, body = _last_query(fake_client)
        assert body["record_id"] == shared_id

    def test_shared_and_owned_ids_do_not_collide(self, surreal_db, fake_client):
        """A shared re-ingest (base id) and an owner (``id:owner``) land on
        distinct records, so a shared write never wipes an owned row."""
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="alice")
        _sql_a, alice_body = _last_query(fake_client)
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id=None)
        _sql_s, shared_body = _last_query(fake_client)
        assert alice_body["record_id"] == f"{shared_id}:alice"
        assert shared_body["record_id"] == shared_id
        assert alice_body["record_id"] != shared_body["record_id"]


class TestSearchIsolationContract:
    """The load-bearing contract: a scoped search restricts the WHERE clause to
    the caller's own rows OR the shared (NONE) bucket, and binds the owner as
    ``$scope_user_id`` — another owner is excluded by construction. Admin
    (``None``) applies no scope."""

    OWN_OR_SHARED = "AND (user_id = $scope_user_id OR user_id = NONE)"

    def test_scoped_search_restricts_to_own_or_shared(self, surreal_db, fake_client):
        surreal_db.search("salary", limit=10, user_id="alice")
        sql, params = _last_query(fake_client)
        assert self.OWN_OR_SHARED in sql
        assert params["scope_user_id"] == "alice"
        # Owner bound as a variable, never spliced into the SQL text.
        assert "alice" not in sql

    def test_admin_search_has_no_scope(self, surreal_db, fake_client):
        surreal_db.search("salary", limit=10, user_id=None)
        sql, params = _last_query(fake_client)
        assert "$scope_user_id" not in sql
        assert "scope_user_id" not in params

    def test_scoped_search_ands_scope_onto_caller_filter(self, surreal_db, fake_client):
        surreal_db.search("salary", limit=10, filters={"topic": "hr"}, user_id="alice")
        sql, params = _last_query(fake_client)
        # Both the caller's own metadata filter AND the owner scope apply.
        assert "meta_data.topic = $topic" in sql
        assert self.OWN_OR_SHARED in sql
        assert params["scope_user_id"] == "alice"
        assert params["topic"] == "hr"

    def test_scope_condition_helper_matches(self):
        # Guards the exact predicate the two search methods share.
        assert SurrealDb._user_scope_condition("alice") == self.OWN_OR_SHARED
        assert SurrealDb._user_scope_condition(None) == ""


class TestScopedDedup:
    """SurrealDB dedups by record id (no delete-by-hash), and the owner is folded
    into that id. So an owner's upsert targets ``id:owner`` while another owner /
    the shared bucket targets a different record — one owner's re-ingest can never
    clear another owner's identical-content row."""

    def test_owner_upsert_targets_only_own_record(self, surreal_db, fake_client):
        shared_id = str(uuid.uuid4())
        # Bob re-ingests content whose id alice also used.
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("Same content", shared_id)], user_id="bob")
        _sql, bob_body = _last_query(fake_client)
        # Bob's UPSERT is keyed on bob's folded id, so it cannot touch
        # ``{id}:alice`` or the bare shared id.
        assert bob_body["record_id"] == f"{shared_id}:bob"
        assert bob_body["record_id"] != f"{shared_id}:alice"
        assert bob_body["record_id"] != shared_id

    def test_upsert_binds_record_id_as_param(self, surreal_db, fake_client):
        # The UPSERT statement targets ``type::record($table, $record_id)`` — the
        # id is a bound variable, so the dedup key is never string-built into SQL.
        shared_id = str(uuid.uuid4())
        surreal_db.upsert(content_hash="h", documents=[_doc_with_id("c", shared_id)], user_id="alice")
        sql, body = _last_query(fake_client)
        assert "type::record($table, $record_id)" in sql
        assert body["table"] == COLLECTION
        assert body["record_id"] == f"{shared_id}:alice"


class TestDeleteByContentIdIsolation:
    """``delete_by_content_id(content_id, user_id=...)`` must scope to the
    caller's chunks — otherwise Bob could guess Alice's content_id and wipe her
    chunks. Unscoped (``None``) is the legacy wipe-everyone behaviour."""

    def test_scoped_delete_binds_owner(self, surreal_db, fake_client):
        surreal_db.delete_by_content_id("doc-1", user_id="bob")
        sql, params = _last_query(fake_client)
        assert "content_id = $content_id" in sql
        assert "AND user_id = $user_id" in sql
        assert params == {"content_id": "doc-1", "user_id": "bob"}

    def test_unscoped_delete_is_content_id_only(self, surreal_db, fake_client):
        surreal_db.delete_by_content_id("doc-1", user_id=None)
        sql, params = _last_query(fake_client)
        assert "content_id = $content_id" in sql
        assert "user_id" not in sql
        assert params == {"content_id": "doc-1"}


class TestKeyInjectionSafety:
    """A quote/keyword-laden ``user_id`` must be bound as a variable, never
    string-interpolated into the SQL — so it lands verbatim as the owner and
    cannot widen the scope."""

    EVIL = "alice' OR user_id = NONE OR '1'='1"

    def test_insert_owner_is_verbatim_literal(self, surreal_db, fake_client):
        surreal_db.insert(content_hash="h1", documents=[_doc("alice content")], user_id=self.EVIL)
        assert _last_create_body(fake_client)["user_id"] == self.EVIL

    def test_search_scope_binds_not_interpolates(self, surreal_db, fake_client):
        surreal_db.search("content", limit=10, user_id=self.EVIL)
        sql, params = _last_query(fake_client)
        assert self.EVIL not in sql  # would appear if interpolated
        assert params["scope_user_id"] == self.EVIL
        assert "$scope_user_id" in sql

    def test_delete_scope_binds_not_interpolates(self, surreal_db, fake_client):
        surreal_db.delete_by_content_id("doc-1", user_id=self.EVIL)
        sql, params = _last_query(fake_client)
        assert self.EVIL not in sql
        assert params["user_id"] == self.EVIL
        assert "$user_id" in sql

    def test_upsert_record_id_binds_not_interpolates(self, surreal_db, fake_client):
        surreal_db.upsert(content_hash="h1", documents=[_doc_with_id("c", str(uuid.uuid4()))], user_id=self.EVIL)
        sql, body = _last_query(fake_client)
        # The evil owner rides inside the bound record_id/user_id, never the SQL.
        assert self.EVIL not in sql
        assert body["user_id"] == self.EVIL
        assert body["record_id"].endswith(f":{self.EVIL}")


class TestAsyncIsolation:
    """The isolation contract must hold identically on the async surface."""

    async def test_async_insert_stamps_owner(self, async_surreal_db, fake_async_client):
        await async_surreal_db.async_insert(content_hash="ha", documents=[_doc("Alice salary")], user_id="alice")
        assert fake_async_client.creates[-1][1]["user_id"] == "alice"

    async def test_async_insert_none_is_shared(self, async_surreal_db, fake_async_client):
        await async_surreal_db.async_insert(content_hash="hs", documents=[_doc("Office closed")], user_id=None)
        assert fake_async_client.creates[-1][1]["user_id"] is SHARED_MARKER

    async def test_async_search_scopes_to_own_or_shared(self, async_surreal_db, fake_async_client):
        await async_surreal_db.async_search("salary", limit=10, user_id="alice")
        sql, params = fake_async_client.queries[-1]
        assert "AND (user_id = $scope_user_id OR user_id = NONE)" in sql
        assert params["scope_user_id"] == "alice"
        assert "alice" not in sql

    async def test_async_admin_search_has_no_scope(self, async_surreal_db, fake_async_client):
        await async_surreal_db.async_search("salary", limit=10, user_id=None)
        sql, params = fake_async_client.queries[-1]
        assert "$scope_user_id" not in sql
        assert "scope_user_id" not in params

    async def test_async_upsert_two_owners_distinct_record_ids(self, async_surreal_db, fake_async_client):
        shared_id = str(uuid.uuid4())
        await async_surreal_db.async_upsert(
            content_hash="h", documents=[_doc_with_id("Same", shared_id)], user_id="alice"
        )
        alice_rid = fake_async_client.queries[-1][1]["record_id"]
        await async_surreal_db.async_upsert(
            content_hash="h", documents=[_doc_with_id("Same", shared_id)], user_id="bob"
        )
        bob_rid = fake_async_client.queries[-1][1]["record_id"]
        assert alice_rid == f"{shared_id}:alice"
        assert bob_rid == f"{shared_id}:bob"
        assert alice_rid != bob_rid
