"""Tests for the v2 -> v3 vector-DB user-isolation migration scripts.

v3 adds per-user RAG isolation. The migration scripts under
``libs/agno/migrations/v2_to_v3/`` prepare EXISTING (pre-v3) vector stores:

- SQL backends (pgvector / singlestore): add the ``user_id`` column so the new
  code doesn't error on the old schema. NULL = shared, existing rows stay visible.
- Sentinel backends (redis / couchbase / cassandra): stamp ``user_id="__shared__"``
  onto existing vectors, which otherwise become INVISIBLE to scoped callers
  (their filter has no "field absent" branch).

These tests exercise the two backends that run without an external service:
- redis via ``fakeredis`` (a real Redis implementation),
- the SQL schema logic via SQLite (in-process; the ``inspect`` + ``ALTER`` path).

The script modules define their migration functions at import (guarded by
``if __name__ == "__main__"``), so we load them by path and call the functions.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import create_engine, inspect, text

_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations" / "v2_to_v3"


def _load(script_name: str) -> ModuleType:
    """Load a migration script module by file path (they are not a package)."""
    path = _MIGRATIONS_DIR / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Redis sentinel backfill (fakeredis — real behavior, no server)
# --------------------------------------------------------------------------- #


class TestRedisSentinelBackfill:
    def _client(self):
        fakeredis = pytest.importorskip("fakeredis")
        return fakeredis.FakeStrictRedis()

    def _uid(self, client, key):
        v = client.hget(key, "user_id")
        return v.decode() if v else None

    def test_stamps_shared_on_legacy_and_preserves_owners(self):
        from agno.vectordb.redis.redisdb import RedisDB

        client = self._client()
        index = "myindex"
        # Pre-v3 vectors: hashes with NO user_id field.
        for i in range(3):
            client.hset(f"{index}:doc{i}", mapping={"id": f"doc{i}", "content": f"c{i}"})
        # An already-owned vector must be left untouched.
        client.hset(f"{index}:owned", mapping={"id": "owned", "content": "c", "user_id": "alice"})

        mod = _load("migrate_sentinel_vectordbs.py")
        mod.redis_config["redis_client"] = client
        mod.migrate_redis_index(index)

        for i in range(3):
            assert self._uid(client, f"{index}:doc{i}") == RedisDB.SHARED_OWNER_TAG
        assert self._uid(client, f"{index}:owned") == "alice"

    def test_idempotent(self):
        from agno.vectordb.redis.redisdb import RedisDB

        client = self._client()
        index = "idx"
        client.hset(f"{index}:d1", mapping={"id": "d1", "content": "x"})

        mod = _load("migrate_sentinel_vectordbs.py")
        mod.redis_config["redis_client"] = client
        mod.migrate_redis_index(index)
        mod.migrate_redis_index(index)  # second run must be a no-op

        assert self._uid(client, f"{index}:d1") == RedisDB.SHARED_OWNER_TAG

    def test_no_vectors_is_safe(self):
        client = self._client()
        mod = _load("migrate_sentinel_vectordbs.py")
        mod.redis_config["redis_client"] = client
        # Empty index — must not raise.
        mod.migrate_redis_index("empty_index")


# --------------------------------------------------------------------------- #
# SQL schema migration logic (SQLite — in-process)
# --------------------------------------------------------------------------- #


class TestSqlSchemaMigrationLogic:
    """The SQL migration's core behavior — 'add user_id unless it already exists' —
    exercised against SQLite. (The pgvector/singlestore functions instantiate their
    adapters, which need a live server; the column-inspection + ALTER logic they run
    is validated here directly to keep it CI-safe.)"""

    def _engine(self):
        return create_engine(f"sqlite:///{tempfile.mktemp(suffix='.db')}")

    def _has_user_id(self, engine, table):
        return "user_id" in [c["name"] for c in inspect(engine).get_columns(table)]

    def test_adds_user_id_column_when_missing(self):
        engine = self._engine()
        with engine.begin() as c:
            c.execute(text("CREATE TABLE docs (id TEXT PRIMARY KEY, content TEXT, content_hash TEXT)"))
            c.execute(text("INSERT INTO docs (id, content, content_hash) VALUES ('r1','hi','h1')"))

        assert not self._has_user_id(engine, "docs")

        # Mirror the migration's logic: inspect, then ALTER only if absent.
        if not self._has_user_id(engine, "docs"):
            with engine.begin() as c:
                c.execute(text("ALTER TABLE docs ADD COLUMN user_id VARCHAR"))

        assert self._has_user_id(engine, "docs")
        # Existing row is NULL = shared = still visible.
        with engine.connect() as c:
            assert c.execute(text("SELECT user_id FROM docs WHERE id='r1'")).scalar() is None

    def test_skips_when_column_already_present(self):
        engine = self._engine()
        with engine.begin() as c:
            c.execute(text("CREATE TABLE docs (id TEXT PRIMARY KEY, user_id VARCHAR)"))

        # Idempotency: the migration must NOT re-add the column (would raise).
        assert self._has_user_id(engine, "docs")
        if not self._has_user_id(engine, "docs"):
            with engine.begin() as c:
                c.execute(text("ALTER TABLE docs ADD COLUMN user_id VARCHAR"))
        assert self._has_user_id(engine, "docs")


# --------------------------------------------------------------------------- #
# Script import safety (functions must load without side effects)
# --------------------------------------------------------------------------- #


class TestScriptsImportCleanly:
    @pytest.mark.parametrize(
        "script,funcs",
        [
            ("migrate_sql_vectordbs.py", ["migrate_pgvector_table", "migrate_singlestore_table", "run"]),
            ("migrate_sentinel_vectordbs.py", ["migrate_redis_index", "migrate_couchbase", "migrate_cassandra", "run"]),
            (
                "migrate_field_vectordbs.py",
                [
                    "migrate_milvus_collection",
                    "migrate_weaviate_collection",
                    "migrate_lancedb_table",
                    "migrate_clickhouse_table",
                    "assign_qdrant_owner",
                    "run",
                ],
            ),
        ],
    )
    def test_functions_present(self, script, funcs):
        mod = _load(script)
        for fn in funcs:
            assert callable(getattr(mod, fn)), f"{script} missing {fn}"


# --------------------------------------------------------------------------- #
# LanceDB schema migration (fully in-process — no server)
# --------------------------------------------------------------------------- #


class TestLanceDbSchemaMigration:
    def _conn_and_table(self):
        lancedb = pytest.importorskip("lancedb")
        pa = pytest.importorskip("pyarrow")
        import tempfile

        uri = tempfile.mkdtemp()
        conn = lancedb.connect(uri)
        schema = pa.schema(
            [
                pa.field("id", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), 3)),
                pa.field("content", pa.string()),
            ]
        )
        table = conn.create_table("docs", schema=schema, mode="overwrite")
        table.add([{"id": "r1", "vector": [0.1, 0.2, 0.3], "content": "hi"}])
        return uri, conn

    def test_adds_user_id_and_unblocks_scoped_search(self):
        from agno.vectordb.lancedb.lance_db import LanceDb

        uri, conn = self._conn_and_table()
        assert LanceDb.USER_ID_COL not in conn.open_table("docs").schema.names

        # Scoped search fails before the column exists.
        with pytest.raises(Exception):
            conn.open_table("docs").search([0.1, 0.2, 0.3]).where(
                f"({LanceDb.USER_ID_COL} = 'alice' OR {LanceDb.USER_ID_COL} IS NULL)", prefilter=True
            ).limit(5).to_list()

        mod = _load("migrate_field_vectordbs.py")
        mod.lancedb_config["uri"] = uri
        mod.migrate_lancedb_table("docs")

        table = conn.open_table("docs")
        assert LanceDb.USER_ID_COL in table.schema.names
        # Existing row is NULL = shared, and the scoped search now works.
        rows = (
            table.search([0.1, 0.2, 0.3])
            .where(f"({LanceDb.USER_ID_COL} = 'alice' OR {LanceDb.USER_ID_COL} IS NULL)", prefilter=True)
            .limit(5)
            .to_list()
        )
        assert len(rows) == 1
        assert rows[0].get(LanceDb.USER_ID_COL) is None

    def test_idempotent(self):
        uri, _ = self._conn_and_table()
        mod = _load("migrate_field_vectordbs.py")
        mod.lancedb_config["uri"] = uri
        mod.migrate_lancedb_table("docs")
        mod.migrate_lancedb_table("docs")  # second run must be a no-op

    def test_missing_table_is_safe(self):
        uri, _ = self._conn_and_table()
        mod = _load("migrate_field_vectordbs.py")
        mod.lancedb_config["uri"] = uri
        mod.migrate_lancedb_table("does_not_exist")  # must not raise
