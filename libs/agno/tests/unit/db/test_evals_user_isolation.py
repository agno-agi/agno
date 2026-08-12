"""Unit tests for per-user eval-run isolation.

Locks in the contract that eval-run reads/writes/deletes scope by ``user_id``
when one is supplied (the OS passes the caller's id under user_isolation), and
stay global when it is ``None`` (single-user / admin).

Every Db adapter implements this contract; the embedded backends (SQLite,
in-memory, JSON) are exercised here so the suite needs no external services.
"""

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.json import JsonDb
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.db.sqlite import SqliteDb


@pytest.fixture(params=["sqlite", "in_memory", "json"])
def db(request, tmp_path):
    if request.param == "sqlite":
        return SqliteDb(db_file=str(tmp_path / "evals_isolation.db"))
    if request.param == "in_memory":
        return InMemoryDb()
    return JsonDb(db_path=str(tmp_path / "evals_isolation_json"))


def _make(db, run_id, user_id):
    # The eval framework persists the run; the OS sets the owner afterwards.
    db.create_eval_run(
        EvalRunRecord(
            run_id=run_id,
            eval_type=EvalType.ACCURACY,
            eval_data={"eval_status": "PASSED"},
            eval_input={},
        )
    )
    if user_id is not None:
        db.update_eval_run_user_id(run_id, user_id)


class TestScopedReads:
    def test_list_scoped_to_owner(self, db):
        _make(db, "r_alice", "alice")
        _make(db, "r_bob", "bob")

        alice_rows, alice_total = db.get_eval_runs(user_id="alice", deserialize=False)
        assert [r["run_id"] for r in alice_rows] == ["r_alice"]
        assert alice_total == 1

    def test_list_unscoped_sees_all(self, db):
        """user_id=None (admin / single-user) sees every run."""
        _make(db, "r_alice", "alice")
        _make(db, "r_bob", "bob")

        rows, total = db.get_eval_runs(deserialize=False)
        assert {r["run_id"] for r in rows} == {"r_alice", "r_bob"}
        assert total == 2

    def test_get_run_ownership(self, db):
        _make(db, "r_alice", "alice")

        assert db.get_eval_run("r_alice", user_id="alice") is not None
        assert db.get_eval_run("r_alice", user_id="bob") is None  # cross-user blocked
        assert db.get_eval_run("r_alice") is not None  # unscoped (admin) sees it


class TestScopedWrites:
    def test_delete_scoped(self, db):
        _make(db, "r_alice", "alice")
        _make(db, "r_bob", "bob")

        # bob cannot delete alice's run
        db.delete_eval_runs(["r_alice"], user_id="bob")
        assert db.get_eval_run("r_alice") is not None

        # alice can delete her own
        db.delete_eval_runs(["r_alice"], user_id="alice")
        assert db.get_eval_run("r_alice") is None
        # bob's run untouched
        assert db.get_eval_run("r_bob") is not None

    def test_rename_scoped(self, db):
        _make(db, "r_alice", "alice")

        # bob cannot rename alice's run -> returns None, name unchanged
        assert db.rename_eval_run("r_alice", "hacked", user_id="bob") is None
        assert db.get_eval_run("r_alice", deserialize=False)["name"] != "hacked"  # type: ignore

        # alice can rename her own
        renamed = db.rename_eval_run("r_alice", "my eval", user_id="alice")
        assert renamed is not None
        assert db.get_eval_run("r_alice", deserialize=False)["name"] == "my eval"  # type: ignore


class TestOwnerStamping:
    def test_update_eval_run_user_id(self, db):
        """The OS stamps the owner after the eval framework persists an unowned run."""
        _make(db, "r_new", None)  # framework writes with no owner
        assert db.get_eval_run("r_new", deserialize=False).get("user_id") is None  # type: ignore

        db.update_eval_run_user_id("r_new", "alice")

        assert db.get_eval_run("r_new", user_id="alice") is not None
        assert db.get_eval_run("r_new", user_id="bob") is None


class TestNoCrossLeak:
    def test_totals_are_per_user(self, db):
        for i in range(3):
            _make(db, f"a{i}", "alice")
        for i in range(2):
            _make(db, f"b{i}", "bob")

        _, alice_total = db.get_eval_runs(user_id="alice", deserialize=False)
        _, bob_total = db.get_eval_runs(user_id="bob", deserialize=False)
        _, grand_total = db.get_eval_runs(deserialize=False)
        assert (alice_total, bob_total, grand_total) == (3, 2, 5)


# ---------------------------------------------------------------------------
# Contract checks — no server needed, so every adapter is covered in CI
# ---------------------------------------------------------------------------

_EVAL_ADAPTERS: list[tuple[str, str]] = [
    ("agno.db.json.json_db", "JsonDb"),
    ("agno.db.gcs_json.gcs_json_db", "GcsJsonDb"),
    ("agno.db.in_memory.in_memory_db", "InMemoryDb"),
    ("agno.db.mongo.mongo", "MongoDb"),
    ("agno.db.mongo.async_mongo", "AsyncMongoDb"),
    ("agno.db.redis.redis", "RedisDb"),
    ("agno.db.valkey.valkey", "ValkeyDb"),
    ("agno.db.firestore.firestore", "FirestoreDb"),
    ("agno.db.dynamo.dynamo", "DynamoDb"),
    ("agno.db.surrealdb.surrealdb", "SurrealDb"),
    ("agno.db.postgres.postgres", "PostgresDb"),
    ("agno.db.postgres.async_postgres", "AsyncPostgresDb"),
    ("agno.db.sqlite.sqlite", "SqliteDb"),
    ("agno.db.sqlite.async_sqlite", "AsyncSqliteDb"),
    ("agno.db.mysql.mysql", "MySQLDb"),
    ("agno.db.mysql.async_mysql", "AsyncMySQLDb"),
    ("agno.db.singlestore.singlestore", "SingleStoreDb"),
]

_SCOPED_METHODS = ["get_eval_run", "get_eval_runs", "delete_eval_runs", "rename_eval_run"]


def _try_import_class(module_path: str, class_name: str):
    """Some adapters have optional native drivers. Skip cleanly if one isn't
    installed — the contract is what we're after, not runtime behavior."""
    try:
        module = __import__(module_path, fromlist=[class_name])
        return getattr(module, class_name)
    except Exception as e:
        pytest.skip(f"skip {class_name}: driver unavailable ({type(e).__name__}: {e})")


@pytest.mark.parametrize("module_path,class_name", _EVAL_ADAPTERS)
@pytest.mark.parametrize("method_name", _SCOPED_METHODS)
def test_eval_reads_accept_user_id(module_path: str, class_name: str, method_name: str):
    """Every adapter accepts ``user_id``; without it a scoped caller sees everyone's eval runs."""
    import inspect

    cls = _try_import_class(module_path, class_name)
    method = getattr(cls, method_name, None)
    assert method is not None, f"{class_name}.{method_name} is missing"
    assert "user_id" in inspect.signature(method).parameters, f"{class_name}.{method_name} does not accept user_id"


@pytest.mark.parametrize("module_path,class_name", _EVAL_ADAPTERS)
def test_update_eval_run_user_id_is_implemented(module_path: str, class_name: str):
    """Every adapter overrides ``update_eval_run_user_id``; the base stub raises NotImplementedError."""
    from agno.db.base import AsyncBaseDb, BaseDb

    cls = _try_import_class(module_path, class_name)
    own = cls.update_eval_run_user_id
    assert own is not BaseDb.update_eval_run_user_id, f"{class_name} inherits the BaseDb stub"
    assert own is not AsyncBaseDb.update_eval_run_user_id, f"{class_name} inherits the AsyncBaseDb stub"
