import datetime

import pytest

# calculate_date_metrics is duplicated across every DB backend. These backends
# previously used the None-unsafe `len(session.get("runs", []))` /
# `session.get("session_data", {}).get(...)` form (postgres/sqlite/mongo/firestore
# already guard with `or []` / `or {}`).
BACKEND_MODULES = [
    "agno.db.dynamo.utils",
    "agno.db.gcs_json.utils",
    "agno.db.in_memory.utils",
    "agno.db.json.utils",
    "agno.db.mysql.utils",
    "agno.db.redis.utils",
    "agno.db.singlestore.utils",
    "agno.db.surrealdb.metrics",
]


@pytest.mark.parametrize("module_path", BACKEND_MODULES)
def test_calculate_date_metrics_handles_none_runs_and_session_data(module_path):
    """A persisted session can carry runs=None / session_data=None (the defaults
    when a session has produced no runs yet, or session_data was never set).
    calculate_date_metrics must not crash on those, counting the session with
    zero runs (matching the postgres backend)."""
    module = pytest.importorskip(module_path)

    sessions_data = {
        "agent": [{"user_id": "u1", "runs": None, "session_data": None}],
        "team": [],
        "workflow": [],
    }

    # Before the fix this raised TypeError: object of type 'NoneType' has no len()
    # (runs=None) or AttributeError: 'NoneType' object has no attribute 'get'
    # (session_data=None).
    metrics = module.calculate_date_metrics(datetime.date.today(), sessions_data)

    assert metrics["agent_runs_count"] == 0
    assert metrics["agent_sessions_count"] == 1
