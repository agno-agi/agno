"""Tests for resolve_db_from_config and _clone_db_with_table_overrides.

These cover the db-resolution path used when agents / teams / workflows
are reloaded from persisted component configs, specifically the cases
that have needed follow-up fixes on PR #7508:

- custom table names persist across a registry-backed reload
- the engine/connection pool is shared across reloads (no pool
  proliferation)
- connection metadata (db_url / db_file / db_schema) survives a clone
  round-trip so a re-save isn't unusable
- non-SQL registered db types aren't regressed to db=None
- the registry-miss path falls back to db_from_dict (not a silent drop)
"""

from unittest.mock import Mock

from sqlalchemy import create_engine

from agno.db.postgres.postgres import PostgresDb
from agno.db.sqlite.sqlite import SqliteDb
from agno.db.utils import (
    DB_TABLE_NAME_KEYS,
    _clone_db_with_table_overrides,
    resolve_db_from_config,
)


class _FakeRegistry:
    """Minimal stand-in for agno.registry.Registry used by these tests."""

    def __init__(self, db=None):
        self._db = db

    def get_db(self, db_id):
        if self._db is not None and getattr(self._db, "id", None) == db_id:
            return self._db
        return None


class TestResolveDbFromConfigSqlite:
    def test_no_overrides_returns_registered_instance(self, tmp_path):
        os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
        registry = _FakeRegistry(os_db)

        resolved = resolve_db_from_config(os_db.to_dict(), registry=registry)

        # Same Python object: no clone needed, no new engine allocated.
        assert resolved is os_db

    def test_overrides_return_clone_sharing_engine(self, tmp_path):
        os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
        registry = _FakeRegistry(os_db)

        data = dict(os_db.to_dict())
        data["session_table"] = "custom_sessions"
        data["memory_table"] = "custom_memories"

        resolved = resolve_db_from_config(data, registry=registry)

        assert resolved is not os_db, "expected a clone, not the registered instance"
        assert isinstance(resolved, SqliteDb)
        assert resolved.session_table_name == "custom_sessions"
        assert resolved.memory_table_name == "custom_memories"
        # Non-overridden fields inherit from the registered db.
        assert resolved.knowledge_table_name == os_db.knowledge_table_name
        # Engine / pool is SHARED — repeated loads must not allocate new pools.
        assert resolved.db_engine is os_db.db_engine
        assert resolved.id == os_db.id

    def test_repeated_reloads_share_one_engine(self, tmp_path):
        os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
        registry = _FakeRegistry(os_db)

        data = dict(os_db.to_dict())
        data["session_table"] = "custom_sessions"

        engines = {id(resolve_db_from_config(data, registry=registry).db_engine) for _ in range(5)}

        assert len(engines) == 1, "engine should be shared across reloads, not reallocated"

    def test_clone_carries_db_file_for_roundtrip(self, tmp_path):
        """Regression: the clone must carry db_file so a re-save of the
        component produces a usable config on a subsequent load without
        the registry.
        """
        os_db = SqliteDb(db_file=str(tmp_path / "os.db"))
        registry = _FakeRegistry(os_db)

        data = dict(os_db.to_dict())
        data["session_table"] = "custom_sessions"

        clone = resolve_db_from_config(data, registry=registry)
        assert clone is not None
        assert clone.db_file == os_db.db_file

        # Round-trip: re-serialize and make sure db_file survives so a
        # registry-less from_dict can rebuild the connection.
        reserialized = clone.to_dict()
        assert reserialized["db_file"] == os_db.db_file
        assert reserialized["session_table"] == "custom_sessions"

    def test_no_registry_falls_back_to_db_from_dict(self, tmp_path):
        db_data = {
            "type": "sqlite",
            "db_file": str(tmp_path / "standalone.db"),
            "session_table": "s",
            "memory_table": "m",
        }

        resolved = resolve_db_from_config(db_data, registry=None)

        assert isinstance(resolved, SqliteDb)
        assert resolved.session_table_name == "s"
        assert resolved.memory_table_name == "m"

    def test_registry_miss_falls_back_to_db_from_dict(self, tmp_path):
        # Registry exists but does not hold the id referenced in db_data.
        other_db = SqliteDb(db_file=str(tmp_path / "other.db"))
        registry = _FakeRegistry(other_db)

        db_data = {
            "type": "sqlite",
            "db_file": str(tmp_path / "standalone.db"),
            "id": "not-in-registry",
            "session_table": "s",
        }

        resolved = resolve_db_from_config(db_data, registry=registry)

        # Pre-fix, this path used to silently drop config["db"]; now it
        # rebuilds a fresh instance from the serialized fields.
        assert isinstance(resolved, SqliteDb)
        assert resolved.session_table_name == "s"


class TestResolveDbFromConfigPostgres:
    def test_clone_shares_engine_and_preserves_connection_metadata(self):
        # A real postgres connection isn't available in unit tests, so
        # inject a sqlite engine as a stand-in to exercise the clone
        # logic without hitting the network. We only care about attribute
        # carry-over here.
        engine = create_engine("sqlite:///:memory:")
        os_db = PostgresDb(
            db_url="postgresql://user:pass@host/db",
            db_engine=engine,
            db_schema="ai",
        )
        registry = _FakeRegistry(os_db)

        data = dict(os_db.to_dict())
        data["session_table"] = "custom_pg_sessions"

        clone = resolve_db_from_config(data, registry=registry)

        assert clone is not os_db
        assert isinstance(clone, PostgresDb)
        assert clone.db_engine is os_db.db_engine
        # Connection metadata must round-trip through to_dict so a
        # re-save isn't unusable.
        assert clone.db_url == os_db.db_url
        assert clone.db_schema == os_db.db_schema
        redict = clone.to_dict()
        assert redict["db_url"] == os_db.db_url
        assert redict["db_schema"] == os_db.db_schema
        assert redict["session_table"] == "custom_pg_sessions"


class TestResolveDbFromConfigNonSqlBackend:
    def test_non_sql_registered_db_returns_registered_instance_not_none(self):
        """Regression: non-SQL backends (JsonDb, RedisDb, FirestoreDb,
        DynamoDb, ...) that are in the registry must not regress to
        db=None when the stored config has table-name overrides. The
        cloner doesn't know how to rebuild them, so we fall back to the
        registered instance (with a warning, not a silent drop).
        """
        # Fake a non-SQL BaseDb subclass that the cloner doesn't handle.
        fake_db = Mock()
        fake_db.id = "fake-nosql"
        fake_db.to_dict.return_value = {
            "id": "fake-nosql",
            "type": "redis",
            "session_table": "json_sessions",
            "memory_table": "json_memories",
            "knowledge_table": "agno_knowledge",
        }
        registry = _FakeRegistry(fake_db)

        data = dict(fake_db.to_dict())
        data["session_table"] = "overridden_sessions"

        resolved = resolve_db_from_config(data, registry=registry)

        # Crucially: must not be None. Overrides are silently ignored
        # for non-SQL backends (pre-fix behavior preserved).
        assert resolved is fake_db


class TestCloneDbWithTableOverrides:
    def test_sqlite_clone_applies_overrides(self, tmp_path):
        src = SqliteDb(db_file=str(tmp_path / "src.db"))
        data = {"session_table": "new_s", "memory_table": "new_m"}

        clone = _clone_db_with_table_overrides(src, data)

        assert isinstance(clone, SqliteDb)
        assert clone.session_table_name == "new_s"
        assert clone.memory_table_name == "new_m"
        assert clone.db_engine is src.db_engine
        assert clone.db_file == src.db_file

    def test_only_whitelisted_keys_pass_through(self, tmp_path):
        src = SqliteDb(db_file=str(tmp_path / "src.db"))
        # db_data contains BOTH a legitimate override and a nonsense key;
        # the cloner must ignore unknown keys instead of blowing up.
        data = {
            "session_table": "new_s",
            "bogus_key": "should-be-ignored",
            "db_url": "postgresql://attacker/evil",  # not a table-name key
        }

        clone = _clone_db_with_table_overrides(src, data)

        assert clone is not None
        assert clone.session_table_name == "new_s"
        # Connection metadata comes from src, not from db_data.
        assert clone.db_engine is src.db_engine
        assert clone.db_file == src.db_file

    def test_returns_none_for_unknown_type(self):
        fake = Mock()
        # Not a PostgresDb or SqliteDb — cloner should bail out.
        assert _clone_db_with_table_overrides(fake, {"session_table": "x"}) is None


class TestDbTableNameKeys:
    def test_constant_matches_basedb_init_signature(self):
        """DB_TABLE_NAME_KEYS is consumed by the components router
        whitelist and by override detection. If BaseDb grows a new table
        parameter, this constant must grow with it or overrides will be
        silently dropped for the new table.
        """
        import inspect

        from agno.db.base import BaseDb

        sig = inspect.signature(BaseDb.__init__)
        table_params = {name for name in sig.parameters if name.endswith("_table")}

        assert table_params == set(DB_TABLE_NAME_KEYS), (
            f"DB_TABLE_NAME_KEYS is out of sync with BaseDb.__init__ table parameters.\n"
            f"In BaseDb but missing from constant: {table_params - set(DB_TABLE_NAME_KEYS)}\n"
            f"In constant but missing from BaseDb: {set(DB_TABLE_NAME_KEYS) - table_params}"
        )
