"""get_runs cursor filters, has_unindexed_runs and get_session(include_runs) for the key-value and file stores."""

import asyncio
import importlib
import sys
import types
from typing import Any, Dict, Optional

import pytest

from agno.db.json.json_db import JsonDb
from tests.unit.db.run_cursor_contract import SESSION_ID, check_contract, seed
from tests.unit.db.test_v3_dynamo_migration_compat import _FakeDynamoClient
from tests.unit.db.test_v3_dynamo_migration_compat import _insert_legacy_session as _insert_legacy_dynamo_session
from tests.unit.db.test_v3_gcs_json_migration_compat import _FakeClient as _FakeGcsClient
from tests.unit.db.test_v3_gcs_json_migration_compat import _insert_legacy_session as _insert_legacy_gcs_session
from tests.unit.db.test_v3_json_migration_compat import _insert_legacy_session as _insert_legacy_json_session

fakeredis = pytest.importorskip("fakeredis")

LEGACY_RUNS = [{"run_id": "legacy-1", "agent_id": "agent-1", "status": "COMPLETED"}]


class _ProjectingDynamoClient(_FakeDynamoClient):
    """Fake that honours ProjectionExpression, so a projected read missing an attribute shows up."""

    @staticmethod
    def _project(item: Dict[str, Any], projection: Optional[str], names: Optional[Dict[str, str]]) -> Dict[str, Any]:
        if projection is None:
            return item
        names = names or {}
        attrs = {names.get(token.strip(), token.strip()) for token in projection.split(",")}
        return {k: v for k, v in item.items() if k in attrs}

    def get_item(self, TableName: str, Key: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        response = super().get_item(TableName=TableName, Key=Key)
        if "Item" in response:
            projection = kwargs.get("ProjectionExpression")
            response = {"Item": self._project(response["Item"], projection, kwargs.get("ExpressionAttributeNames"))}
        return response

    def query(self, TableName: str, **kwargs: Any) -> Dict[str, Any]:
        projection = kwargs.pop("ProjectionExpression", None)
        response = super().query(TableName=TableName, **kwargs)
        names = kwargs.get("ExpressionAttributeNames")
        return {"Items": [self._project(it, projection, names) for it in response["Items"]]}


def _json_db(tmp_path):
    return JsonDb(db_path=str(tmp_path))


class _NotFound(Exception):
    pass


def _gcs_db(request, monkeypatch):
    try:
        importlib.import_module("google.cloud.storage")
    except ImportError:
        # google-cloud-storage is optional: stand in for the two modules GcsJsonDb imports,
        # and drop the module imported against them afterwards so other tests see the real state.
        monkeypatch.setitem(sys.modules, "google.cloud.storage", types.ModuleType("google.cloud.storage"))
        monkeypatch.setitem(
            sys.modules,
            "google.cloud.exceptions",
            types.SimpleNamespace(NotFound=_NotFound, GoogleCloudError=Exception),
        )
        import agno.db

        saved = {name: sys.modules.pop(name, None) for name in ("agno.db.gcs_json", "agno.db.gcs_json.gcs_json_db")}
        saved_attr = agno.db.__dict__.get("gcs_json")

        def restore() -> None:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
            if saved_attr is None:
                agno.db.__dict__.pop("gcs_json", None)
            else:
                agno.db.gcs_json = saved_attr  # type: ignore[attr-defined]

        request.addfinalizer(restore)
    mod = importlib.import_module("agno.db.gcs_json.gcs_json_db")
    monkeypatch.setattr(mod, "gcs", types.SimpleNamespace(Client=_FakeGcsClient))
    monkeypatch.setattr(_FakeGcsClient, "_buckets", {})
    return mod.GcsJsonDb(bucket_name="test-bucket", prefix="agno/")


def _redis_db():
    from agno.db.redis.redis import RedisDb

    return RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True), db_prefix="agno")


def _dynamo_db():
    from agno.db.dynamo.dynamo import DynamoDb

    db = DynamoDb(db_client=_ProjectingDynamoClient())
    db._create_all_tables()
    return db


@pytest.fixture(params=["json", "gcs_json", "redis", "dynamo"])
def adapter(request, tmp_path, monkeypatch):
    if request.param == "json":
        return request.param, _json_db(tmp_path)
    if request.param == "gcs_json":
        return request.param, _gcs_db(request, monkeypatch)
    if request.param == "redis":
        return request.param, _redis_db()
    return request.param, _dynamo_db()


def _write_legacy_session(name: str, db: Any, runs: Any) -> None:
    if name == "json":
        _insert_legacy_json_session(db, SESSION_ID, runs)
    elif name == "gcs_json":
        _insert_legacy_gcs_session(db, SESSION_ID, runs)
    elif name == "redis":
        from agno.db.redis.utils import generate_redis_key, serialize_data

        key = generate_redis_key(prefix=db.db_prefix, table_type="sessions", key_id=SESSION_ID)
        db.redis_client.set(
            key, serialize_data({"session_id": SESSION_ID, "session_type": "agent", "user_id": "u1", "runs": runs})
        )
    else:
        _insert_legacy_dynamo_session(db, SESSION_ID, runs)


def test_contract(adapter):
    _, db = adapter
    asyncio.run(check_contract(db))


def test_legacy_blob_is_unindexed(adapter):
    name, db = adapter
    _write_legacy_session(name, db, LEGACY_RUNS)
    assert db.has_unindexed_runs(SESSION_ID) is True


def test_empty_legacy_blob_is_indexed(adapter):
    name, db = adapter
    _write_legacy_session(name, db, [])
    assert db.has_unindexed_runs(SESSION_ID) is False


def test_run_row_without_index_is_unindexed(adapter):
    _, db = adapter
    asyncio.run(seed(db))
    db.upsert_run(run={"run_id": "loose", "agent_id": "agent-1", "status": "COMPLETED"}, session_id=SESSION_ID)
    assert db.has_unindexed_runs(SESSION_ID) is True
    rows, _ = db.get_runs(session_id=SESSION_ID, deserialize=False, after_run_index=-1)
    assert "loose" not in [row["run_id"] for row in rows]


def test_missing_session_is_not_unindexed(adapter):
    _, db = adapter
    assert db.has_unindexed_runs("no-such-session") is False


def test_include_runs_false_skips_runs_store(adapter):
    name, db = adapter
    asyncio.run(seed(db))
    calls = []
    for attr in ("_get_session_runs_data", "_get_session_run_rows", "_read_runs_file", "_query_runs_by_session"):
        if hasattr(db, attr):
            original = getattr(db, attr)
            setattr(db, attr, lambda *a, _o=original, _n=attr, **k: calls.append(_n) or _o(*a, **k))
    db.get_session(session_id=SESSION_ID, deserialize=False)
    assert calls, "the spy must see a default get_session read the runs store"
    calls.clear()
    session = db.get_session(session_id=SESSION_ID, include_runs=False, deserialize=False)
    assert session is not None and session["runs"] is None
    assert calls == []
