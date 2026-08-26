"""Tests for the v2 -> v3 vector-DB user-isolation migration scripts.

The scripts under ``libs/agno/migrations/v2_to_v3/`` add the ``user_id`` column on SQL
backends (NULL = shared) and stamp ``user_id="__shared__"`` on sentinel backends, whose
filters have no "field absent" branch and so cannot see un-stamped vectors. Only the
backends that run without an external service are exercised here.
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


class TestRedisSentinelBackfill:
    def _client(self):
        fakeredis = pytest.importorskip("fakeredis")
        return fakeredis.FakeStrictRedis()

    def _uid(self, client, key):
        v = client.hget(key, "user_id")
        return v.decode() if v else None

    def test_stamps_shared_on_legacy_and_preserves_owners(self):
        from agno.vectordb.redis.redisdb import RedisDb

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
            assert self._uid(client, f"{index}:doc{i}") == RedisDb.SHARED_OWNER_TAG
        assert self._uid(client, f"{index}:owned") == "alice"

    def test_idempotent(self):
        from agno.vectordb.redis.redisdb import RedisDb

        client = self._client()
        index = "idx"
        client.hset(f"{index}:d1", mapping={"id": "d1", "content": "x"})

        mod = _load("migrate_sentinel_vectordbs.py")
        mod.redis_config["redis_client"] = client
        mod.migrate_redis_index(index)
        mod.migrate_redis_index(index)  # second run must be a no-op

        assert self._uid(client, f"{index}:d1") == RedisDb.SHARED_OWNER_TAG

    def test_no_vectors_is_safe(self):
        client = self._client()
        mod = _load("migrate_sentinel_vectordbs.py")
        mod.redis_config["redis_client"] = client
        # Empty index — must not raise.
        mod.migrate_redis_index("empty_index")


class TestSurrealDbSchemaMigration:
    def _conn(self):
        surrealdb = pytest.importorskip("surrealdb")
        conn = surrealdb.Surreal("mem://")
        conn.use("test", "test")
        return conn

    def _fields(self, conn, coll):
        info = conn.query(f"INFO FOR TABLE {coll};")
        info = info[0] if isinstance(info, list) else info
        return list((info or {}).get("fields", {}).keys())

    def test_declares_user_id_field(self):
        conn = self._conn()
        coll = "docs"
        conn.query(f"DEFINE TABLE IF NOT EXISTS {coll} SCHEMAFUL;")
        conn.query(f"DEFINE FIELD IF NOT EXISTS content ON {coll} TYPE string;")
        conn.query(f"CREATE {coll}:r1 SET content='hi';")
        assert "user_id" not in self._fields(conn, coll)

        mod = _load("migrate_field_vectordbs.py")
        mod.surrealdb_config["client"] = conn
        mod.migrate_surrealdb_collection(coll)

        assert "user_id" in self._fields(conn, coll)
        # The existing record reads as NONE (shared), so a scoped read still finds it.
        rows = conn.query(f"SELECT content, user_id FROM {coll} WHERE (user_id = 'alice' OR user_id = NONE);")
        rows = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], list) else rows
        assert rows

    def test_idempotent(self):
        conn = self._conn()
        coll = "docs2"
        conn.query(f"DEFINE TABLE IF NOT EXISTS {coll} SCHEMAFUL;")
        mod = _load("migrate_field_vectordbs.py")
        mod.surrealdb_config["client"] = conn
        mod.migrate_surrealdb_collection(coll)
        mod.migrate_surrealdb_collection(coll)  # second run must be a no-op
        assert "user_id" in self._fields(conn, coll)


class TestSqlSchemaMigrationLogic:
    """The SQL migration's core behavior — 'add user_id unless it already exists' — against SQLite.

    The pgvector/singlestore functions instantiate adapters that need a live server, so the
    column-inspection + ALTER logic they run is exercised directly here.
    """

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


class TestWeaviateRefusesInPlaceMigration:
    """Weaviate cannot be migrated in place: the shared filter needs a create-time ``index_null_state``.

    It can't be added later, so the migration must refuse a pre-v3 collection with a recreate
    instruction — adding the ``user_id`` property would leave ``Knowledge.insert`` broken.
    """

    def _mock_client(self, existing_props, exists=True):
        import sys
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        pytest.importorskip("weaviate")
        client = MagicMock()
        client.collections.exists.return_value = exists
        props = [SimpleNamespace(name=p) for p in existing_props]
        client.collections.get.return_value.config.get.return_value.properties = props
        # Patch the module-level connect_to_local so the migration gets our mock.
        import weaviate

        self._orig = weaviate.connect_to_local
        weaviate.connect_to_local = lambda **kw: client
        sys.modules["weaviate"].connect_to_local = weaviate.connect_to_local
        return client

    def _restore(self):
        import weaviate

        weaviate.connect_to_local = self._orig

    def test_pre_v3_collection_refuses_with_recreate_instruction(self):
        mod = _load("migrate_field_vectordbs.py")
        client = self._mock_client(existing_props=["content"])  # no user_id -> pre-v3
        try:
            with pytest.raises(RuntimeError) as exc:
                mod.migrate_weaviate_collection("Docs")
            msg = str(exc.value).lower()
            assert "recreate" in msg
            assert "index_null_state" in msg
            client.collections.get.return_value.config.add_property.assert_not_called()
        finally:
            self._restore()

    def test_v3_collection_is_a_noop(self):
        from agno.vectordb.weaviate.weaviate import Weaviate

        mod = _load("migrate_field_vectordbs.py")
        client = self._mock_client(existing_props=["content", Weaviate.USER_ID_KEY])
        try:
            mod.migrate_weaviate_collection("Docs")  # must not raise
            client.collections.get.return_value.config.add_property.assert_not_called()
        finally:
            self._restore()

    def test_missing_collection_is_safe(self):
        mod = _load("migrate_field_vectordbs.py")
        self._mock_client(existing_props=[], exists=False)
        try:
            mod.migrate_weaviate_collection("Nope")  # must not raise
        finally:
            self._restore()


class TestQdrantOwnerAssignment:
    def test_set_payload_assigns_owner_in_place(self):
        qdrant_client = pytest.importorskip("qdrant_client")
        from qdrant_client import models

        from agno.vectordb.qdrant.qdrant import Qdrant

        client = qdrant_client.QdrantClient(":memory:")
        client.create_collection("docs", vectors_config=models.VectorParams(size=3, distance=models.Distance.COSINE))
        client.upsert(
            "docs",
            points=[
                models.PointStruct(id=1, vector=[0.1, 0.2, 0.3], payload={"content": "a"}),
                models.PointStruct(id=2, vector=[0.4, 0.5, 0.6], payload={"content": "b"}),
            ],
        )
        payload = lambda pid: client.retrieve("docs", [pid])[0].payload  # noqa: E731
        assert payload(1).get(Qdrant.USER_ID_KEY) is None  # existing = shared

        # What assign_qdrant_owner does via set_payload.
        client.set_payload(collection_name="docs", payload={Qdrant.USER_ID_KEY: "alice"}, points=[1])

        assert payload(1).get(Qdrant.USER_ID_KEY) == "alice"
        assert payload(2).get(Qdrant.USER_ID_KEY) is None  # untouched, still shared


class TestScriptsImportCleanly:
    @pytest.mark.parametrize(
        "script,funcs",
        [
            ("migrate_sql_vectordbs.py", ["migrate_pgvector_table", "migrate_singlestore_table", "run"]),
            (
                "migrate_sentinel_vectordbs.py",
                ["migrate_redis_index", "migrate_couchbase", "migrate_cassandra", "run"],
            ),
            (
                "migrate_field_vectordbs.py",
                [
                    "migrate_milvus_collection",
                    "migrate_weaviate_collection",
                    "migrate_lancedb_table",
                    "migrate_clickhouse_table",
                    "migrate_surrealdb_collection",
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


class TestMilvusMigrationContract:
    """No-server guards: the migration must stay in sync with the adapter's constants."""

    def test_adapter_exposes_the_constants_the_migration_depends_on(self):
        # Renaming these again (as USER_ID_KEY was) must fail here, not at call time.
        milvus = pytest.importorskip("agno.vectordb.milvus.milvus")
        assert isinstance(milvus.USER_ID_FIELD, str) and milvus.USER_ID_FIELD
        assert isinstance(milvus.SHARED_USER_ID_VALUE, str) and milvus.SHARED_USER_ID_VALUE

    def test_migration_does_not_reference_the_removed_attribute(self):
        # Only the Milvus form is banned — Weaviate/Qdrant still expose USER_ID_KEY.
        source = (_MIGRATIONS_DIR / "migrate_field_vectordbs.py").read_text()
        assert "Milvus.USER_ID_KEY" not in source, "migration references removed attribute Milvus.USER_ID_KEY"
        assert "SHARED_USER_ID_VALUE" in source, "migration must backfill the shared sentinel"


class TestMilvusBackfill:
    """Full backfill behavior on milvus-lite.

    milvus-lite cannot ``AddCollectionField`` (UNIMPLEMENTED, like Milvus <=2.5), so the
    collection is pre-created with a nullable ``user_id`` and owner-less rows — the state a
    real 2.6+ server is in right after ``add_collection_field``.
    """

    def _client_with_legacy_rows(self):
        pytest.importorskip("milvus_lite")
        from pymilvus import DataType, MilvusClient

        from agno.vectordb.milvus.milvus import USER_ID_FIELD

        uri = str(Path(tempfile.mkdtemp()) / "milvus.db")
        client = MilvusClient(uri=uri)
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("id", DataType.VARCHAR, max_length=128, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=4)
        schema.add_field(USER_ID_FIELD, DataType.VARCHAR, max_length=256, nullable=True)
        idx = client.prepare_index_params()
        idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
        client.create_collection(collection_name="docs", schema=schema, index_params=idx)
        client.insert(
            collection_name="docs",
            data=[
                {"id": "doc_a", "vector": [0.1, 0.2, 0.3, 0.4], USER_ID_FIELD: ""},
                {"id": "doc_b", "vector": [0.5, 0.6, 0.7, 0.8], USER_ID_FIELD: ""},
            ],
        )
        client.flush(collection_name="docs")
        return uri, client

    def test_backfill_stamps_shared_and_unblocks_scoped_search(self):
        from agno.vectordb.milvus.milvus import SHARED_USER_ID_VALUE, USER_ID_FIELD

        uri, client = self._client_with_legacy_rows()
        mod = _load("migrate_field_vectordbs.py")
        mod.milvus_config["uri"] = uri
        mod.milvus_config["token"] = None
        mod.migrate_milvus_collection("docs")

        client.load_collection("docs")
        rows = client.query(collection_name="docs", filter="id != ''", output_fields=[USER_ID_FIELD])
        assert rows and all(r.get(USER_ID_FIELD) == SHARED_USER_ID_VALUE for r in rows)

        # Existing rows are now reachable by a scoped search.
        scoped = client.query(
            collection_name="docs",
            filter=f'{USER_ID_FIELD} == "alice" or {USER_ID_FIELD} == "{SHARED_USER_ID_VALUE}"',
            output_fields=["id"],
        )
        assert len(scoped) == 2

    def test_idempotent(self):
        from agno.vectordb.milvus.milvus import SHARED_USER_ID_VALUE, USER_ID_FIELD

        uri, client = self._client_with_legacy_rows()
        mod = _load("migrate_field_vectordbs.py")
        mod.milvus_config["uri"] = uri
        mod.milvus_config["token"] = None
        mod.migrate_milvus_collection("docs")
        mod.migrate_milvus_collection("docs")  # second run must be a no-op

        client.load_collection("docs")
        rows = client.query(collection_name="docs", filter="id != ''", output_fields=[USER_ID_FIELD])
        assert all(r.get(USER_ID_FIELD) == SHARED_USER_ID_VALUE for r in rows)

    def test_missing_collection_is_safe(self):
        pytest.importorskip("milvus_lite")
        uri = str(Path(tempfile.mkdtemp()) / "milvus.db")
        mod = _load("migrate_field_vectordbs.py")
        mod.milvus_config["uri"] = uri
        mod.milvus_config["token"] = None
        mod.migrate_milvus_collection("does_not_exist")  # must not raise
