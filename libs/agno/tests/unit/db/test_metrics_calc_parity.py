"""Parity tests for ``calculate_date_metrics`` across all SQL backends.

The SQL family (sqlite, postgres, mysql, singlestore) each ship their own
copy of ``calculate_date_metrics`` in their respective ``utils.py``. After
the per-user metrics refactor, every copy must produce byte-identical
records for the same input — drift would mean RBAC-on deployments see
different metrics depending on backend, which is a correctness bug.

We use sqlite's helper as the reference and assert every other backend's
helper matches it field-for-field (excluding ephemeral id/created_at/updated_at).
"""

from datetime import date
from typing import Callable, Dict, List

import pytest

from agno.db.sqlite.utils import calculate_date_metrics as sqlite_calc


def _calc_postgres():
    from agno.db.postgres.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_mysql():
    from agno.db.mysql.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_singlestore():
    from agno.db.singlestore.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_mongo():
    from agno.db.mongo.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_surreal():
    from agno.db.surrealdb.metrics import calculate_date_metrics

    return calculate_date_metrics


def _calc_redis():
    from agno.db.redis.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_dynamo():
    from agno.db.dynamo.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_firestore():
    from agno.db.firestore.utils import calculate_date_metrics

    return calculate_date_metrics


BACKEND_CALCS: List[tuple] = [
    ("postgres", _calc_postgres),
    ("mysql", _calc_mysql),
    ("singlestore", _calc_singlestore),
    ("mongo", _calc_mongo),
    # SQLite reference uses uuid IDs and ``int(time.time())`` timestamps;
    # the backends below produce identical bucket counts and token metrics
    # but use deterministic per-(date, user_id) string IDs and/or
    # backend-specific date/timestamp shapes. They're tested by the looser
    # "buckets-and-counts" assertion below instead of byte-parity.
    ("redis", _calc_redis),
    ("dynamo", _calc_dynamo),
]


# Backends that use a string isoformat date and/or different ID scheme but
# whose per-user buckets must still match SQLite for counts/token_metrics.
LOOSE_PARITY_BACKENDS = [
    ("surrealdb", _calc_surreal),
    ("firestore", _calc_firestore),
]


def _calc_in_memory():
    from agno.db.in_memory.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_json():
    from agno.db.json.utils import calculate_date_metrics

    return calculate_date_metrics


def _calc_gcs_json():
    from agno.db.gcs_json.utils import calculate_date_metrics

    return calculate_date_metrics


LOOSE_PARITY_BACKENDS += [
    ("in_memory", _calc_in_memory),
    ("json", _calc_json),
    ("gcs_json", _calc_gcs_json),
]


def _session(uid, runs=1, tokens=0, model="gpt-5", provider="openai"):
    """Build a fake session row. Used for agent / team / workflow sessions —
    they share the same schema; only the bucket the caller drops them into
    differs."""
    return {
        "user_id": uid,
        "runs": [{"model": model, "model_provider": provider} for _ in range(runs)],
        "session_data": {"session_metrics": {"input_tokens": tokens, "total_tokens": tokens}},
    }


# Kept as an alias for the agent-only callsites below.
_agent = _session


# Each tuple: (label, sessions_data) — the cases we want to assert parity on.
CASES = [
    (
        "single_user",
        {"agent": [_agent("alice", runs=2, tokens=5)], "team": [], "workflow": []},
    ),
    (
        "two_users_plus_unowned",
        {
            "agent": [
                _agent("alice", runs=1, tokens=10),
                _agent("bob", runs=3, tokens=7),
                _agent(None, runs=2, tokens=3),
            ],
            "team": [],
            "workflow": [],
        },
    ),
    (
        "only_unowned",
        {"agent": [_agent(None, runs=1, tokens=2)], "team": [], "workflow": []},
    ),
    (
        "empty",
        {"agent": [], "team": [], "workflow": []},
    ),
    # --- Cases that exercise team + workflow + mixed session types ---
    (
        "team_only_single_user",
        {
            "agent": [],
            "team": [_session("alice", runs=2, tokens=4)],
            "workflow": [],
        },
    ),
    (
        "workflow_only_single_user",
        {
            "agent": [],
            "team": [],
            "workflow": [_session("alice", runs=3, tokens=6)],
        },
    ),
    (
        "mixed_session_types_one_user",
        {
            "agent": [_session("alice", runs=1, tokens=10)],
            "team": [_session("alice", runs=2, tokens=5)],
            "workflow": [_session("alice", runs=1, tokens=3)],
        },
    ),
    (
        "mixed_session_types_multi_user",
        # Alice has all three; Bob has agent + team only; an unowned workflow
        # session lands in the empty-string bucket. Tests that team + workflow
        # rows get attributed to the correct user_id (per-user bucketing).
        {
            "agent": [
                _session("alice", runs=1, tokens=10),
                _session("bob", runs=2, tokens=5),
            ],
            "team": [
                _session("alice", runs=3, tokens=4),
                _session("bob", runs=1, tokens=2),
            ],
            "workflow": [
                _session("alice", runs=2, tokens=6),
                _session(None, runs=1, tokens=1),
            ],
        },
    ),
    (
        "multi_model_per_bucket",
        # Same user spans multiple models in one run set. Exercises the
        # ``model_counts`` -> ``model_metrics`` per-user nesting.
        {
            "agent": [
                {
                    "user_id": "alice",
                    "runs": [
                        {"model": "gpt-5", "model_provider": "openai"},
                        {"model": "gpt-5", "model_provider": "openai"},
                        {"model": "claude-opus", "model_provider": "anthropic"},
                    ],
                    "session_data": {"session_metrics": {"input_tokens": 7, "total_tokens": 9}},
                },
            ],
            "team": [],
            "workflow": [],
        },
    ),
]

# Fields that legitimately differ between runs (uuid, timestamps).
EPHEMERAL = {"id", "created_at", "updated_at"}


def _normalize(recs: List[dict]) -> Dict[str, dict]:
    """Group a list of records by user_id, strip ephemeral fields."""
    return {r["user_id"]: {k: v for k, v in r.items() if k not in EPHEMERAL} for r in recs}


@pytest.mark.parametrize("backend, get_calc", BACKEND_CALCS, ids=[b for b, _ in BACKEND_CALCS])
@pytest.mark.parametrize("case_label, sessions_data", CASES, ids=[c for c, _ in CASES])
def test_backend_matches_sqlite_reference(backend: str, get_calc: Callable, case_label: str, sessions_data: dict):
    backend_calc = get_calc()
    target_date = date(2026, 1, 1)
    backend_recs = backend_calc(target_date, sessions_data)
    sqlite_recs = sqlite_calc(target_date, sessions_data)
    assert _normalize(backend_recs) == _normalize(sqlite_recs), (
        f"backend={backend} case={case_label}: calculate_date_metrics drift from SQLite reference"
    )


# SurrealDB intentionally uses backend-specific id/date/timestamp shapes
# (deterministic per-(date, user) string ID; native datetime for date/created_at/
# updated_at). We assert the per-user bucketing + counts separately so we
# still get coverage of the aggregation contract without comparing field
# shapes that legitimately differ.
SURREAL_NUMERIC_FIELDS = (
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


@pytest.mark.parametrize("backend, get_calc", LOOSE_PARITY_BACKENDS, ids=[b for b, _ in LOOSE_PARITY_BACKENDS])
@pytest.mark.parametrize("case_label, sessions_data", CASES, ids=[c for c, _ in CASES])
def test_loose_parity_buckets_and_counts_match_sqlite(backend: str, get_calc, case_label: str, sessions_data: dict):
    """Backends that ship their own ID/date/timestamp shapes still need to
    produce the same per-user bucket set and the same counts/token metrics
    as the SQLite reference. We don't compare the ID or date field shapes
    here — those legitimately differ — but everything aggregated MUST
    match."""
    backend_calc = get_calc()
    target_date = date(2026, 1, 1)
    backend_by_user = {r["user_id"]: r for r in backend_calc(target_date, sessions_data)}
    sqlite_by_user = {r["user_id"]: r for r in sqlite_calc(target_date, sessions_data)}

    assert set(backend_by_user) == set(sqlite_by_user), (
        f"backend={backend} case={case_label}: per-user bucket set drift vs sqlite"
    )
    for uid in backend_by_user:
        for field in SURREAL_NUMERIC_FIELDS:
            assert backend_by_user[uid][field] == sqlite_by_user[uid][field], (
                f"backend={backend} case={case_label} uid={uid!r} field={field}: drift vs sqlite"
            )
