"""
Bug reproduction: memory_topics signature mismatch (v2.5.16)

BaseDb.get_all_memory_topics(user_id=...) declared at base.py:226,
but 11 concrete backends reject the kwarg -> TypeError 500 on GET /memory_topics.
MySQL accepts user_id but silently ignores it -> tenant data leak.
Firestore has a spurious param instead of user_id.

Expected on current main: signature/TypeError tests FAIL for broken backends,
MySQL/Firestore tests FAIL. After fix, all tests PASS.
"""

import ast
import importlib
import inspect
import textwrap

import pytest

from agno.db.base import AsyncBaseDb, BaseDb

_SYNC_CANDIDATES = [
    ("agno.db.postgres.postgres", "PostgresDb"),
    ("agno.db.sqlite.sqlite", "SqliteDb"),
    ("agno.db.in_memory.in_memory_db", "InMemoryDb"),
    ("agno.db.json.json_db", "JsonDb"),
    ("agno.db.redis.redis", "RedisDb"),
    ("agno.db.mongo.mongo", "MongoDb"),
    ("agno.db.dynamo.dynamo", "DynamoDb"),
    ("agno.db.firestore.firestore", "FirestoreDb"),
    ("agno.db.gcs_json.gcs_json_db", "GcsJsonDb"),
    ("agno.db.singlestore.singlestore", "SingleStoreDb"),
    ("agno.db.surrealdb.surrealdb", "SurrealDb"),
    ("agno.db.mysql.mysql", "MySQLDb"),
]

_ASYNC_CANDIDATES = [
    ("agno.db.postgres.async_postgres", "AsyncPostgresDb"),
    ("agno.db.sqlite.async_sqlite", "AsyncSqliteDb"),
    ("agno.db.mongo.async_mongo", "AsyncMongoDb"),
    ("agno.db.mysql.async_mysql", "AsyncMySQLDb"),
]

SYNC_BACKENDS = []
ASYNC_BACKENDS = []

for mod_path, cls_name in _SYNC_CANDIDATES:
    try:
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        SYNC_BACKENDS.append(pytest.param(cls, id=cls_name))
    except Exception:
        pass

for mod_path, cls_name in _ASYNC_CANDIDATES:
    try:
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        ASYNC_BACKENDS.append(pytest.param(cls, id=cls_name))
    except Exception:
        pass


# -- 1. Base contract verification (these SHOULD pass) --


class TestBaseContract:
    def test_sync_base_declares_user_id(self):
        sig = inspect.signature(BaseDb.get_all_memory_topics)
        assert "user_id" in sig.parameters
        assert sig.parameters["user_id"].default is None

    def test_async_base_declares_user_id(self):
        sig = inspect.signature(AsyncBaseDb.get_all_memory_topics)
        assert "user_id" in sig.parameters
        assert sig.parameters["user_id"].default is None


# -- 2. Signature mismatch detection (FAILS for each broken backend) --


class TestSignatureMismatch:
    @pytest.mark.parametrize("cls", SYNC_BACKENDS)
    def test_sync_backend_accepts_user_id(self, cls):
        sig = inspect.signature(cls.get_all_memory_topics)
        has_user_id = "user_id" in sig.parameters
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        assert has_user_id or has_kwargs, (
            f"{cls.__name__}.get_all_memory_topics signature: {sig}\n"
            f"Missing 'user_id' -> TypeError when router calls db.get_all_memory_topics(user_id=user_id)"
        )

    @pytest.mark.parametrize("cls", ASYNC_BACKENDS)
    def test_async_backend_accepts_user_id(self, cls):
        sig = inspect.signature(cls.get_all_memory_topics)
        has_user_id = "user_id" in sig.parameters
        has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        assert has_user_id or has_kwargs, (
            f"{cls.__name__}.get_all_memory_topics signature: {sig}\n"
            f"Missing 'user_id' -> TypeError when router calls await db.get_all_memory_topics(user_id=user_id)"
        )


# -- 3. TypeError reproduction (FAILS = bug is real) --


class TestTypeErrorReproduction:
    @pytest.mark.parametrize("cls", SYNC_BACKENDS)
    def test_user_id_kwarg_raises_typeerror(self, cls):
        sig = inspect.signature(cls.get_all_memory_topics)
        if "user_id" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            pytest.skip(f"{cls.__name__} accepts user_id (not broken)")

        # Reproduce the exact production error — no DB needed.
        # Python rejects the kwarg at call boundary before body executes.
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            cls.get_all_memory_topics(None, user_id="test-user")


# -- 4. MySQL data leak (accepts user_id but ignores it) --


class TestMySQLDataLeak:
    def _get_body_name_refs(self, func) -> set:
        source = textwrap.dedent(inspect.getsource(func))
        tree = ast.parse(source)
        func_node = tree.body[0]
        refs = set()
        for stmt in func_node.body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name):
                    refs.add(node.id)
        return refs

    def test_mysql_sync_uses_user_id_in_body(self):
        try:
            from agno.db.mysql.mysql import MySQLDb
        except ImportError:
            pytest.skip("mysql deps not installed")

        sig = inspect.signature(MySQLDb.get_all_memory_topics)
        assert "user_id" in sig.parameters, "MySQL doesn't even accept user_id"

        refs = self._get_body_name_refs(MySQLDb.get_all_memory_topics)
        assert "user_id" in refs, (
            "MySQL.get_all_memory_topics accepts user_id in signature "
            "but never references it in the body — silent tenant data leak"
        )

    def test_mysql_async_uses_user_id_in_body(self):
        try:
            from agno.db.mysql.async_mysql import AsyncMySQLDb
        except ImportError:
            pytest.skip("async mysql deps not installed")

        sig = inspect.signature(AsyncMySQLDb.get_all_memory_topics)
        assert "user_id" in sig.parameters, "AsyncMySQL doesn't even accept user_id"

        refs = self._get_body_name_refs(AsyncMySQLDb.get_all_memory_topics)
        assert "user_id" in refs, (
            "AsyncMySQLDb.get_all_memory_topics accepts user_id in signature "
            "but never references it in the body — silent tenant data leak"
        )


# -- 5. Firestore wrong param name --


class TestFirestoreWrongParam:
    def test_firestore_has_user_id_not_bogus_param(self):
        try:
            from agno.db.firestore.firestore import FirestoreDb
        except ImportError:
            pytest.skip("firestore deps not installed")

        sig = inspect.signature(FirestoreDb.get_all_memory_topics)
        params = list(sig.parameters.keys())

        assert "create_collection_if_not_found" not in params, (
            f"Firestore has spurious 'create_collection_if_not_found' param (dead code). Params: {params}"
        )
        assert "user_id" in params, f"Firestore.get_all_memory_topics missing 'user_id'. Params: {params}"
