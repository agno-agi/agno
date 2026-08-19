"""Parity tests for ``calculate_date_metrics`` across every backend.

Each adapter ships its own copy of the helper, and every copy must bucket by
``user_id`` identically. SQLite is the reference: ``STRICT`` backends match it
field for field once the ephemeral id/timestamp fields are stripped, while
``LOOSE`` backends ship their own id/date/timestamp shapes, so only the per-user
buckets and the aggregated numbers are compared.
"""

import importlib
from datetime import date
from typing import Dict, List

import pytest

from agno.db.sqlite.utils import calculate_date_metrics as sqlite_calc

STRICT = [
    "agno.db.postgres.utils",
    "agno.db.mysql.utils",
    "agno.db.singlestore.utils",
    "agno.db.mongo.utils",
    # These build deterministic per-(date, user_id) string ids instead of uuids; the ids are stripped anyway.
    "agno.db.redis.utils",
    "agno.db.valkey.utils",
    "agno.db.dynamo.utils",
]

LOOSE = [
    "agno.db.surrealdb.metrics",
    "agno.db.firestore.utils",
    "agno.db.in_memory.utils",
    "agno.db.json.utils",
    "agno.db.gcs_json.utils",
]

# Fields that legitimately differ between runs (uuid, timestamps).
EPHEMERAL = {"id", "created_at", "updated_at"}

# Everything that carries an aggregated meaning, compared on the LOOSE backends.
AGGREGATED = (
    "users_count",
    "agent_sessions_count",
    "team_sessions_count",
    "workflow_sessions_count",
    "agent_runs_count",
    "team_runs_count",
    "workflow_runs_count",
    "token_metrics",
    "model_metrics",
)

TARGET_DATE = date(2026, 1, 1)


def _calc(module_path: str):
    """Some adapters have optional native drivers; skip cleanly if absent.

    Only a missing driver is skippable. A backend that imports but no longer has the
    function has dropped out of parity, which is the whole point of this file.
    """
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        pytest.skip(f"{module_path}: driver unavailable ({type(e).__name__}: {e})")
    return module.calculate_date_metrics


def _session(uid, runs=1, tokens=0, total=None, models=(("gpt-5", "openai"),)):
    """A fake session row. Agent, team and workflow sessions share this schema."""
    return {
        "user_id": uid,
        "runs": [{"model": m, "model_provider": p} for m, p in models for _ in range(runs)],
        "session_data": {
            "session_metrics": {"input_tokens": tokens, "total_tokens": tokens if total is None else total}
        },
    }


def _data(agent=(), team=(), workflow=()):
    return {"agent": list(agent), "team": list(team), "workflow": list(workflow)}


CASES = {
    "single_user": _data(agent=[_session("alice", runs=2, tokens=5)]),
    "two_users_plus_unowned": _data(
        agent=[
            _session("alice", runs=1, tokens=10),
            _session("bob", runs=3, tokens=7),
            _session(None, runs=2, tokens=3),
        ]
    ),
    "only_unowned": _data(agent=[_session(None, runs=1, tokens=2)]),
    "empty": _data(),
    "team_only_single_user": _data(team=[_session("alice", runs=2, tokens=4)]),
    "workflow_only_single_user": _data(workflow=[_session("alice", runs=3, tokens=6)]),
    "mixed_session_types_one_user": _data(
        agent=[_session("alice", runs=1, tokens=10)],
        team=[_session("alice", runs=2, tokens=5)],
        workflow=[_session("alice", runs=1, tokens=3)],
    ),
    # The unowned workflow session lands in the empty-string bucket.
    "mixed_session_types_multi_user": _data(
        agent=[_session("alice", runs=1, tokens=10), _session("bob", runs=2, tokens=5)],
        team=[_session("alice", runs=3, tokens=4), _session("bob", runs=1, tokens=2)],
        workflow=[_session("alice", runs=2, tokens=6), _session(None, runs=1, tokens=1)],
    ),
    # A NULL session_data column reaches the helper as None.
    "null_session_data": _data(agent=[{**_session("alice"), "session_data": None}]),
    # Sessions that never recorded token usage carry a NULL session_metrics.
    "null_session_metrics": _data(agent=[{**_session("alice"), "session_data": {"session_metrics": None}}]),
    "multi_model_per_bucket": _data(
        agent=[_session("alice", runs=1, tokens=7, total=9, models=(("gpt-5", "openai"), ("claude-opus", "anthropic")))]
    ),
}


def _normalize(recs: List[dict]) -> Dict[str, dict]:
    return {r["user_id"]: {k: v for k, v in r.items() if k not in EPHEMERAL} for r in recs}


@pytest.mark.parametrize("module_path", STRICT)
@pytest.mark.parametrize("case", CASES, ids=list(CASES))
def test_strict_backend_matches_sqlite(module_path: str, case: str):
    records = _calc(module_path)(TARGET_DATE, CASES[case])
    assert _normalize(records) == _normalize(sqlite_calc(TARGET_DATE, CASES[case]))


@pytest.mark.parametrize("module_path", LOOSE)
@pytest.mark.parametrize("case", CASES, ids=list(CASES))
def test_loose_backend_buckets_and_counts_match_sqlite(module_path: str, case: str):
    """Different id/date/timestamp shapes, but the same buckets and the same aggregated numbers."""
    backend = {r["user_id"]: r for r in _calc(module_path)(TARGET_DATE, CASES[case])}
    reference = {r["user_id"]: r for r in sqlite_calc(TARGET_DATE, CASES[case])}

    assert set(backend) == set(reference)
    for uid in backend:
        assert {f: backend[uid][f] for f in AGGREGATED} == {f: reference[uid][f] for f in AGGREGATED}
