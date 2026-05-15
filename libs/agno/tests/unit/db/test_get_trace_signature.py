"""Regression test: every DB backend's ``get_trace`` accepts the kwargs the
trace router passes (``user_id``, ``session_id``, ``agent_id``).

Without this, adding user_id scoping to ``GET /traces/{trace_id}`` silently
500s on every backend except sqlite because the route passes a kwarg the
implementation doesn't accept (TypeError caught by the route's bare except).
"""

from __future__ import annotations

import importlib
import inspect
from typing import List, Tuple

import pytest

REQUIRED_KWARGS = {"trace_id", "run_id", "session_id", "user_id", "agent_id"}

# (module path, class name) — covers every concrete BaseDb / AsyncBaseDb subclass.
BACKENDS: List[Tuple[str, str]] = [
    ("agno.db.postgres.postgres", "PostgresDb"),
    ("agno.db.postgres.async_postgres", "AsyncPostgresDb"),
    ("agno.db.mysql.mysql", "MySQLDb"),
    ("agno.db.mysql.async_mysql", "AsyncMySQLDb"),
    ("agno.db.sqlite.sqlite", "SqliteDb"),
    ("agno.db.sqlite.async_sqlite", "AsyncSqliteDb"),
    ("agno.db.singlestore.singlestore", "SingleStoreDb"),
    ("agno.db.mongo.mongo", "MongoDb"),
    ("agno.db.mongo.async_mongo", "AsyncMongoDb"),
    ("agno.db.dynamo.dynamo", "DynamoDb"),
    ("agno.db.firestore.firestore", "FirestoreDb"),
    ("agno.db.redis.redis", "RedisDb"),
    ("agno.db.json.json_db", "JsonDb"),
    ("agno.db.in_memory.in_memory_db", "InMemoryDb"),
    ("agno.db.gcs_json.gcs_json_db", "GcsJsonDb"),
    ("agno.db.surrealdb.surrealdb", "SurrealDb"),
]


@pytest.mark.parametrize(("module_path", "class_name"), BACKENDS)
def test_get_trace_accepts_required_kwargs(module_path: str, class_name: str) -> None:
    """Every concrete backend's ``get_trace`` must accept the trace router's kwargs."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        pytest.skip(f"Backend {module_path} not installed: {exc}")

    db_cls = getattr(module, class_name, None)
    if db_cls is None:
        pytest.fail(f"{class_name} not found in {module_path}")

    method = getattr(db_cls, "get_trace", None)
    assert method is not None, f"{class_name} is missing get_trace"

    sig = inspect.signature(method)
    params = set(sig.parameters)
    missing = REQUIRED_KWARGS - params
    assert not missing, (
        f"{class_name}.get_trace is missing required kwargs: {missing}. "
        f"The traces router passes user_id/session_id/agent_id; backends that "
        f"don't accept them will TypeError at call time."
    )
