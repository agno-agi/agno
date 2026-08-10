"""Tests for the legacy-schema (pre-v3) fallback across the vector DBs.

The contract, agreed for v3:
- store missing the ``user_id`` column/field + ``user_id=None``  -> behave
  byte-for-byte like main (v2): no owner references anywhere.
- store missing the column/field + a real ``user_id``            -> raise a
  clear ValueError naming the v2 -> v3 migration; never a raw driver error,
  never a silent ``[]`` / ``False``.
- store migrated while the process is alive                      -> the gate
  re-inspects once before refusing, so scoped ops recover without a restart.

The gate-contract tests exercise every backend's ``_require_owner_*`` gate
directly (no server needed). The LanceDB tests then prove the full behavior
against a real (embedded) engine: a byte-accurate v2 table end to end.
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
    from agno.vectordb.redis import RedisDB

    db = RedisDB(index_name="t", redis_url="redis://localhost:1", embedder=StubEmbedder())
    return db, "_user_id_field_exists", db._require_owner_field


def _make_valkey():
    pytest.importorskip("glide_sync")
    from agno.vectordb.valkey import ValkeyDB

    db = ValkeyDB(index_name="t", glide_client=MagicMock(), embedder=StubEmbedder())
    return db, "_user_id_field_exists", db._require_owner_field


def _make_weaviate():
    pytest.importorskip("weaviate")
    from agno.vectordb.weaviate import Weaviate

    db = Weaviate(collection="T", client=MagicMock(), embedder=StubEmbedder())
    return db, "_user_id_property_exists", db._require_owner_property


BACKENDS = {
    "pgvector": _make_pgvector,
    "clickhouse": _make_clickhouse,
    "singlestore": _make_singlestore,
    "lancedb": _make_lancedb,
    "redis": _make_redis,
    "valkey": _make_valkey,
    "weaviate": _make_weaviate,
}


def _build(name, tmp_path):
    factory = BACKENDS[name]
    return factory(tmp_path) if name == "lancedb" else factory()


@pytest.mark.parametrize("backend", BACKENDS)
def test_unscoped_on_legacy_store_falls_back(backend, tmp_path, monkeypatch):
    """Path 1: column missing + user_id=None -> proceed WITHOUT owner references."""
    db, probe_name, gate = _build(backend, tmp_path)
    monkeypatch.setattr(db, probe_name, lambda: False)

    assert gate(None) is False


@pytest.mark.parametrize("backend", BACKENDS)
def test_scoped_on_legacy_store_raises_migration_error(backend, tmp_path, monkeypatch):
    """Path 2: column missing + real user_id -> clear error naming the migration."""
    db, probe_name, gate = _build(backend, tmp_path)
    monkeypatch.setattr(db, probe_name, lambda: False)

    with pytest.raises(ValueError, match="migration"):
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
    """A store migrated while the process is alive recovers without a restart.

    The probe answers False (stale cache), then True (post-migration): the
    gate must re-inspect once before refusing. Regression test for the
    ClickHouse bug where a cached False was refused forever.
    """
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
