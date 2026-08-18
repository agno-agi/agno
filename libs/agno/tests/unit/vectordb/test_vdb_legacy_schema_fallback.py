"""Tests for the legacy-schema (pre-v3) fallback across the vector DBs.

A store without the ``user_id`` column/field serves unscoped calls exactly as v2 did,
raises a ValueError naming the v2 -> v3 migration on scoped calls, and recovers without a
restart once migrated. The gate tests cover every backend against mocks; the LanceDB tests
run the same contract against a real (embedded) v2 table.
"""

from __future__ import annotations

import hashlib
import json
import struct
from unittest.mock import MagicMock

import pytest

DIM = 8


class StubEmbedder:
    """Deterministic embedder — no network, stable across runs."""

    dimensions = DIM
    enable_batch = False

    def _vec(self, text: str):
        digest = hashlib.sha256(text.encode()).digest()
        return [struct.unpack("<f", digest[i * 4 : i * 4 + 4])[0] % 1.0 for i in range(DIM)]

    def get_embedding(self, text: str):
        return self._vec(text)

    def get_embedding_and_usage(self, text: str):
        return self._vec(text), None


# ---------------------------------------------------------------------------
# Gate contract, per backend
# ---------------------------------------------------------------------------


def _make_pgvector():
    pytest.importorskip("pgvector")
    from agno.vectordb.pgvector import PgVector

    db = PgVector(table_name="t", db_url="postgresql+psycopg://u:p@localhost:1/x", embedder=StubEmbedder())
    return db, "_user_id_column_exists", db._require_owner_column


def _make_clickhouse():
    pytest.importorskip("clickhouse_connect")
    from agno.vectordb.clickhouse import Clickhouse

    db = Clickhouse(table_name="t", host="localhost", client=MagicMock(), embedder=StubEmbedder())
    return db, "_user_id_column_exists", db._require_owner_column


def _make_singlestore():
    from agno.vectordb.singlestore import SingleStore

    db = SingleStore(collection="t", db_engine=MagicMock(), embedder=StubEmbedder())
    return db, "_user_id_column_exists", db._require_owner_column


def _make_lancedb(tmp_path):
    pytest.importorskip("lancedb")
    from agno.vectordb.lancedb import LanceDb

    db = LanceDb(uri=str(tmp_path), table_name="t", embedder=StubEmbedder())
    return db, "_user_id_column_exists", db._require_owner_column


def _make_redis():
    pytest.importorskip("redisvl")
    from agno.vectordb.redis import RedisDb

    db = RedisDb(index_name="t", redis_url="redis://localhost:1", embedder=StubEmbedder())
    return db, "_user_id_field_exists", db._require_owner_field


def _make_weaviate():
    pytest.importorskip("weaviate")
    from agno.vectordb.weaviate import Weaviate

    db = Weaviate(collection="T", client=MagicMock(), embedder=StubEmbedder())
    return db, "_user_id_property_exists", db._require_owner_property


def _make_opensearch():
    pytest.importorskip("opensearchpy")
    from agno.vectordb.opensearch import OpenSearch

    db = OpenSearch(index_name="t", dimension=DIM, embedder=StubEmbedder())
    # The gate inspects the live mapping, so the client must never reach a real cluster.
    db._client = MagicMock()
    return db, "_owner_field_is_exact", db._require_owner_field


BACKENDS = {
    "pgvector": _make_pgvector,
    "clickhouse": _make_clickhouse,
    "singlestore": _make_singlestore,
    "lancedb": _make_lancedb,
    "redis": _make_redis,
    "weaviate": _make_weaviate,
    "opensearch": _make_opensearch,
}


def _build(name, tmp_path):
    factory = BACKENDS[name]
    return factory(tmp_path) if name == "lancedb" else factory()


@pytest.mark.parametrize("backend", BACKENDS)
def test_unscoped_on_legacy_store_falls_back(backend, tmp_path, monkeypatch):
    """Column missing + user_id=None -> proceed WITHOUT owner references."""
    db, probe_name, gate = _build(backend, tmp_path)
    monkeypatch.setattr(db, probe_name, lambda: False)

    assert gate(None) is False


@pytest.mark.parametrize("backend", BACKENDS)
def test_scoped_on_legacy_store_raises_migration_error(backend, tmp_path, monkeypatch):
    """Column missing + real user_id -> clear error naming the migration."""
    db, probe_name, gate = _build(backend, tmp_path)
    monkeypatch.setattr(db, probe_name, lambda: False)

    # Weaviate says "recreate", not "migration": its index_null_state is create-time-only.
    with pytest.raises(ValueError, match="migration|recreate"):
        gate("alice")


@pytest.mark.parametrize("backend", BACKENDS)
def test_migrated_store_passes_the_gate(backend, tmp_path, monkeypatch):
    """Column present -> both scoped and unscoped proceed with owner references."""
    db, probe_name, gate = _build(backend, tmp_path)
    monkeypatch.setattr(db, probe_name, lambda: True)

    assert gate(None) is True
    assert gate("alice") is True


@pytest.mark.parametrize("backend", BACKENDS)
def test_gate_reinspects_after_live_migration(backend, tmp_path, monkeypatch):
    """A store migrated while the process is alive recovers without a restart."""
    db, probe_name, gate = _build(backend, tmp_path)
    answers = [False, True]
    monkeypatch.setattr(db, probe_name, lambda: answers.pop(0))

    assert gate("alice") is True


# ---------------------------------------------------------------------------
# Full behavior on a real engine (embedded LanceDB, byte-accurate v2 table)
# ---------------------------------------------------------------------------


@pytest.fixture()
def legacy_lance(tmp_path):
    lancedb = pytest.importorskip("lancedb")
    pa = pytest.importorskip("pyarrow")
    from agno.vectordb.lancedb import LanceDb

    conn = lancedb.connect(str(tmp_path))
    schema = pa.schema(
        [
            pa.field("vector", pa.list_(pa.float32(), DIM)),
            pa.field("id", pa.string()),
            pa.field("payload", pa.string()),
        ]
    )
    table = conn.create_table("legacy", schema=schema)
    embedder = StubEmbedder()
    table.add(
        [
            {
                "vector": embedder.get_embedding("legacy shared holiday calendar"),
                "id": "legacy-1",
                "payload": json.dumps(
                    {
                        "name": "legacy-doc",
                        "meta_data": {},
                        "content": "legacy shared holiday calendar",
                        "usage": None,
                        "content_id": "cid-legacy",
                        "content_hash": "aaaa1111",
                    }
                ),
            }
        ]
    )
    return LanceDb(uri=str(tmp_path), table_name="legacy", embedder=embedder)


def _doc(doc_id, name, content, content_id):
    from agno.knowledge.document import Document

    return Document(id=doc_id, name=name, content=content, content_id=content_id)


def test_lancedb_unscoped_flows_behave_like_v2(legacy_lance):
    db = legacy_lance

    db.insert("bbbb2222", [_doc("a-1", "a", "alpha onboarding guide", "cid-a")])

    db.upsert("cccc3333", [_doc("b-1", "b", "beta expense policy", "cid-b")])
    db.upsert("cccc3333", [_doc("b-1", "b", "beta expense policy", "cid-b")])
    rows = db.table.search().select(["payload"]).limit(100).to_list()
    matching = [r for r in rows if json.loads(r["payload"]).get("content_hash") == "cccc3333"]
    assert len(matching) == 1, "re-upsert must dedupe via the content_hash-only fallback"

    results = db.search("holiday calendar", limit=5)
    assert any("legacy shared" in d.content for d in results)

    assert db.delete_by_content_id("cid-a") is True


def test_lancedb_scoped_flows_raise_on_legacy_table(legacy_lance):
    db = legacy_lance

    for operation in (
        lambda: db.search("x", limit=5, user_id="alice"),
        lambda: db.insert("dddd4444", [_doc("i", "i", "i", "ci")], user_id="alice"),
        lambda: db.upsert("eeee5555", [_doc("u", "u", "u", "cu")], user_id="alice"),
        lambda: db.delete_by_content_id("cid-legacy", user_id="alice"),
    ):
        with pytest.raises(ValueError, match="migration"):
            operation()


def test_lancedb_scoped_flows_recover_after_migration(legacy_lance):
    db = legacy_lance

    db.table.add_columns({"user_id": "CAST(NULL AS STRING)"})

    db.upsert("ffff6666", [_doc("al-1", "alice-doc", "alice private budget", "cid-al")], user_id="alice")
    db.upsert("abab7777", [_doc("bo-1", "bob-doc", "bob private budget", "cid-bo")], user_id="bob")

    alice_view = db.search("budget", limit=10, user_id="alice")
    contents = " ".join(d.content for d in alice_view)
    assert "alice private" in contents
    assert "bob private" not in contents, "isolation leak: alice sees bob's doc"
    legacy_view = db.search("holiday calendar", limit=10, user_id="alice")
    assert any("legacy shared" in d.content for d in legacy_view), "legacy rows must read as shared"

    admin_view = db.search("budget", limit=10)
    admin_contents = " ".join(d.content for d in admin_view)
    assert "alice private" in admin_contents and "bob private" in admin_contents


def test_weaviate_gate_requires_null_state_indexing_not_just_the_property():
    """``add_property`` alone must not pass the gate: shared-bucket filters run ``is_none(user_id)``,
    which Weaviate refuses without create-time ``index_null_state``."""
    pytest.importorskip("weaviate")
    from types import SimpleNamespace

    from agno.vectordb.weaviate import Weaviate

    def _db_with(null_state: bool):
        client = MagicMock()
        client.is_connected.return_value = True
        config = SimpleNamespace(
            properties=[SimpleNamespace(name="user_id"), SimpleNamespace(name="content_hash")],
            inverted_index_config=SimpleNamespace(index_null_state=null_state),
        )
        client.collections.get.return_value.config.get.return_value = config
        return Weaviate(collection="T", client=client, embedder=StubEmbedder())

    # Half-migrated: property present, null-state off.
    assert _db_with(null_state=False)._user_id_property_exists() is False

    # Fully v3: both create-time pieces present.
    assert _db_with(null_state=True)._user_id_property_exists() is True


def test_surrealdb_create_after_drop_redefines_the_schema():
    """``drop()`` must clear the once-per-instance schema flag, or ``create()`` after it is a no-op."""
    pytest.importorskip("surrealdb")
    from agno.vectordb.surrealdb import SurrealDb

    client = MagicMock()
    db = SurrealDb(client=client, collection="t", embedder=StubEmbedder())

    db.create()
    assert db._schema_ensured is True
    define_calls = client.query.call_count

    db.drop()
    assert db._schema_ensured is False, "drop() must force the DEFINEs to re-run"

    db.create()
    assert client.query.call_count == define_calls + 2, "create() after drop() must re-run the DEFINEs"


@pytest.mark.parametrize("backend", ["clickhouse", "redis", "weaviate"])
def test_drop_resets_the_owner_schema_cache(backend, tmp_path, monkeypatch):
    """``drop()`` must clear the cached schema answer, or a stale False refuses scoped ops
    on the next store created under the same name."""
    db, probe_name, _gate = _build(backend, tmp_path)
    cache_attr = {
        "clickhouse": "_owner_column_exists",
        "redis": "_owner_field_exists",
        "weaviate": "_owner_property_exists",
    }[backend]
    setattr(db, cache_attr, False)
    # Redis builds a real SearchIndex from the URL — swap it so delete() skips the TCP connect.
    if backend == "redis":
        db.index = MagicMock()
    if backend == "valkey":
        # drop()'s key sweep never terminates on a MagicMock cursor.
        monkeypatch.setattr(db, "_delete_all_keys", lambda: None)
    monkeypatch.setattr(db, "exists", lambda: True, raising=False)
    monkeypatch.setattr(db, "table_exists", lambda: True, raising=False)

    db.drop()

    assert getattr(db, cache_attr) is None, "drop() must invalidate the cached schema answer"


def test_lancedb_gate_recovers_from_migration_by_another_process(legacy_lance):
    """The gate recovers when another process migrates the table: a pinned LanceTable handle
    re-reads the stale schema forever, so the re-inspect must ``checkout_latest()`` first."""
    import lancedb

    db = legacy_lance

    # Cache the legacy answer on the app's handle.
    with pytest.raises(ValueError, match="migration"):
        db.search("x", limit=1, user_id="alice")

    # Migrate through a separate handle, standing in for a different process.
    other_handle = lancedb.connect(str(db.uri)).open_table("legacy")
    other_handle.add_columns({"user_id": "CAST(NULL AS STRING)"})
    assert "user_id" not in db.table.schema.names, "app handle must still be pinned to the stale version"

    # The next scoped op on the app's handle must recover, not re-raise.
    db.upsert("cdcd8888", [_doc("al-1", "alice-doc", "alice private budget", "cid-al")], user_id="alice")
    results = db.search("budget", limit=5, user_id="alice")
    assert any("alice private" in d.content for d in results)


def test_qdrant_write_ensures_tenant_index_on_preexisting_collection():
    """A pre-v3 collection never reaches create(), so the write path must ensure the tenant
    payload index itself, once per instance."""
    pytest.importorskip("qdrant_client")
    from agno.knowledge.document import Document
    from agno.vectordb.qdrant import Qdrant

    db = Qdrant(collection="t", url="http://localhost:1", embedder=StubEmbedder())
    db._client = MagicMock()  # pre-existing collection: create() is never called

    doc = Document(id="d1", name="d", content="hello world", content_id="c1")
    db.insert("hash-1", [doc])
    assert db.client.create_payload_index.call_count == 1, "first write must ensure the tenant index"

    db.insert("hash-2", [doc])
    assert db.client.create_payload_index.call_count == 1, "ensure is once per instance"


# ---------------------------------------------------------------------------
# Inconclusive inspections are never cached
# ---------------------------------------------------------------------------
# A failed inspection assumes "migrated" for that call only: caching it would mask a real
# legacy store silently, since the swallowed unknown-column errors read as an empty knowledge base.


def test_pgvector_probe_blip_is_not_cached(monkeypatch):
    pytest.importorskip("pgvector")
    from agno.vectordb.pgvector import PgVector

    db = PgVector(table_name="t", db_url="postgresql+psycopg://u:p@localhost:1/x", embedder=StubEmbedder())
    calls = {"n": 0}

    def fake_inspect(engine):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient blip")
        inspector = MagicMock()
        inspector.get_columns.return_value = [{"name": "content_hash"}]  # legacy: no user_id
        return inspector

    monkeypatch.setattr("agno.vectordb.pgvector.pgvector.inspect", fake_inspect)

    assert db._user_id_column_exists() is True  # blip -> assume migrated
    assert db._owner_column_exists is None, "an inconclusive answer must not be cached"
    assert db._user_id_column_exists() is False  # re-probe lands the truth
    assert db._owner_column_exists is False, "a conclusive answer is cached"


def test_pgvector_missing_table_is_cached_as_migrated(monkeypatch):
    pytest.importorskip("pgvector")
    from sqlalchemy.exc import NoSuchTableError

    from agno.vectordb.pgvector import PgVector

    db = PgVector(table_name="t", db_url="postgresql+psycopg://u:p@localhost:1/x", embedder=StubEmbedder())

    def fake_inspect(engine):
        inspector = MagicMock()
        inspector.get_columns.side_effect = NoSuchTableError("t")
        return inspector

    monkeypatch.setattr("agno.vectordb.pgvector.pgvector.inspect", fake_inspect)

    assert db._user_id_column_exists() is True  # no table yet -> will be created with the column
    assert db._owner_column_exists is True, "store-missing is a conclusive, cacheable answer"


def test_clickhouse_probe_blip_is_not_cached():
    pytest.importorskip("clickhouse_connect")
    from agno.vectordb.clickhouse import Clickhouse

    client = MagicMock()
    client.command.return_value = 1  # table exists
    client.query.side_effect = [RuntimeError("transient blip"), MagicMock(result_rows=[])]
    db = Clickhouse(table_name="t", host="localhost", client=client, embedder=StubEmbedder())

    assert db._user_id_column_exists() is True
    assert db._owner_column_exists is None
    assert db._user_id_column_exists() is False
    assert db._owner_column_exists is False


def test_redis_probe_blip_is_not_cached():
    pytest.importorskip("redisvl")
    from agno.vectordb.redis import RedisDb

    db = RedisDb(index_name="t", redis_url="redis://localhost:1", embedder=StubEmbedder())
    db.index = MagicMock()
    db.index.info.side_effect = [RuntimeError("transient blip"), {"attributes": []}]

    assert db._user_id_field_exists() is True
    assert db._owner_field_exists is None
    assert db._user_id_field_exists() is False
    assert db._owner_field_exists is False


def test_redis_create_warns_only_on_conclusive_legacy_verdict(caplog):
    pytest.importorskip("redisvl")
    import logging

    from agno.vectordb.redis import RedisDb

    def _db_with_info(info):
        db = RedisDb(index_name="t", redis_url="redis://localhost:1", embedder=StubEmbedder())
        db.index = MagicMock()
        db.index.exists.return_value = True
        db.index.info.side_effect = info
        return db

    agno_logger = logging.getLogger("agno")
    agno_logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger="agno"):
            _db_with_info([RuntimeError("cannot inspect")]).create()
        assert "was created without" not in caplog.text, "an uninspectable index must not be mis-warned as legacy"

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="agno"):
            _db_with_info([{"attributes": []}]).create()
        assert "was created without" in caplog.text, "a conclusive legacy verdict must warn"
    finally:
        agno_logger.removeHandler(caplog.handler)


def test_weaviate_probe_blip_is_not_cached():
    pytest.importorskip("weaviate")
    from types import SimpleNamespace

    from agno.vectordb.weaviate import Weaviate

    client = MagicMock()
    client.is_connected.return_value = True
    client.collections.exists.return_value = True
    legacy_config = SimpleNamespace(
        properties=[SimpleNamespace(name="content_hash")],
        inverted_index_config=SimpleNamespace(index_null_state=False),
    )
    client.collections.get.return_value.config.get.side_effect = [RuntimeError("transient blip"), legacy_config]
    db = Weaviate(collection="T", client=client, embedder=StubEmbedder())

    assert db._user_id_property_exists() is True
    assert db._owner_property_exists is None
    assert db._user_id_property_exists() is False
    assert db._owner_property_exists is False
