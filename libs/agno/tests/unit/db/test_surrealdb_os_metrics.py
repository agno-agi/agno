"""Unit tests for the OS Metrics related methods of the SurrealDb class"""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest
from surrealdb import RecordID, Surreal

from agno.db.surrealdb import SurrealDb
from agno.db.surrealdb.metrics import desurrealize_os_metric, lock_os_metrics, unlock_os_metrics
from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest.fixture
def surreal_db() -> SurrealDb:
    """Create a SurrealDb on an in-memory engine that runs inside the test process"""
    try:
        client = Surreal("mem://")
    except Exception:
        pytest.skip("surrealdb has no in-process engine")
    client.use("test", "test")
    return SurrealDb(
        client,
        "mem://",
        {},
        "test",
        "test",
        session_table="test_sessions",
        runs_table="test_runs",
        os_metrics_table="test_os_metrics",
        os_metrics_totals_table="test_os_metrics_totals",
    )


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _run_on(day: date, run_id: str, user_id: str, input_tokens: int) -> RunOutput:
    """A completed run created at midday UTC of the given day, with 5 output tokens"""
    tokens = dict(input_tokens=input_tokens, output_tokens=5, total_tokens=input_tokens + 5)
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        user_id=user_id,
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(**tokens, duration=1.5, details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI")]}),
        created_at=int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp()),
    )


def _persist(db: SurrealDb, day: date, session_id: str, user_id: str, input_tokens: int = 10) -> None:
    """Store an agent session created at midday UTC of the given day, then its one run in the runs table"""
    run = _run_on(day, f"{session_id}_run", user_id, input_tokens)
    db.upsert_session(
        AgentSession(session_id=session_id, agent_id="agent-1", user_id=user_id, runs=[run], created_at=run.created_at)
    )
    db.upsert_run(run, session_id=session_id, user_id=user_id, run_index=0)


def _rows(db: SurrealDb, table_type: str) -> List[Dict]:
    """Every row of the given OS metrics table, in the shape calculate_date_os_metrics builds"""
    table = db._get_table(table_type)
    return [desurrealize_os_metric(record) for record in db._query(f"SELECT * FROM {table}", {}, dict)]


@pytest.fixture
def sample_sessions(surreal_db: SurrealDb) -> None:
    """Store one session each for alice and bob two days back, one for alice today, and one for bob 70 days back"""
    _persist(surreal_db, _utc_date(2), "alice_session", "alice", input_tokens=10)
    _persist(surreal_db, _utc_date(2), "bob_session", "bob", input_tokens=20)
    _persist(surreal_db, _utc_date(0), "alice_today_session", "alice", input_tokens=30)
    _persist(surreal_db, _utc_date(70), "bob_old_session", "bob", input_tokens=40)


def test_calculate_os_metrics(surreal_db: SurrealDb, sample_sessions):
    assert surreal_db.calculate_os_metrics()

    rows = {(row["date"], row["user_id"]): row for row in _rows(surreal_db, "os_metrics")}
    daily = {key: row for key, row in rows.items() if row["aggregation_period"] == "daily"}
    assert {key: (row["sessions_count"], row["runs_count"], row["input_tokens"]) for key, row in daily.items()} == {
        (_utc_date(70), "bob"): (1, 1, 40),
        (_utc_date(2), "alice"): (1, 1, 10),
        (_utc_date(2), "bob"): (1, 1, 20),
        (_utc_date(0), "alice"): (1, 1, 30),
    }

    totals = {
        row["date"]: row for row in _rows(surreal_db, "os_metrics_totals") if row["aggregation_period"] == "daily"
    }
    assert sorted(totals) == [_utc_date(days_ago) for days_ago in range(70, -1, -1)]
    assert (totals[_utc_date(2)]["sessions_count"], totals[_utc_date(2)]["input_tokens"]) == (2, 30)
    assert totals[_utc_date(1)]["sessions_count"] == 0
    assert totals[_utc_date(2)]["completed"] is True
    assert totals[_utc_date(1)]["completed"] is False
    assert {row["version"] for row in totals.values()} == {1}


def test_calculate_os_metrics_counts_runs_kept_in_the_legacy_runs_field(surreal_db: SurrealDb):
    """A run not yet migrated out of the session's legacy runs field is counted once, on its session's day"""
    _persist(surreal_db, _utc_date(2), "legacy_session", "alice", input_tokens=10)
    legacy_only_run = _run_on(_utc_date(2), "legacy_only_run", "alice", input_tokens=30)
    stored_run = _run_on(_utc_date(2), "legacy_session_run", "alice", input_tokens=10)
    surreal_db._query(
        "UPDATE $record SET runs = $runs",
        {
            "record": RecordID("test_sessions", "legacy_session"),
            "runs": [stored_run.to_dict(), legacy_only_run.to_dict()],
        },
        dict,
    )

    surreal_db.calculate_os_metrics()

    row = next(row for row in _rows(surreal_db, "os_metrics") if row["aggregation_period"] == "daily")
    assert (row["sessions_count"], row["runs_count"], row["input_tokens"]) == (1, 2, 40)


def test_month_rows(surreal_db: SurrealDb, sample_sessions, monkeypatch):
    monkeypatch.setattr("agno.db.surrealdb.surrealdb.OS_METRICS_BATCH_SIZE", 1)
    _persist(surreal_db, _utc_date(70), "alice_old_session", "alice")
    surreal_db.calculate_os_metrics()

    month_start = _utc_date(70).replace(day=1)
    month_totals = [row for row in _rows(surreal_db, "os_metrics_totals") if row["aggregation_period"] == "monthly"]
    assert month_start in {row["date"] for row in month_totals}
    assert all(row["completed"] for row in month_totals)
    month_rows = [row for row in _rows(surreal_db, "os_metrics") if row["aggregation_period"] == "monthly"]
    assert sorted((row["date"], row["user_id"], row["sessions_count"]) for row in month_rows) == [
        (month_start, "alice", 1),
        (month_start, "bob", 1),
    ]


def test_get_os_metrics(surreal_db: SurrealDb, sample_sessions):
    surreal_db.calculate_os_metrics()
    surreal_db._os_metrics_refreshed_at = time.time()

    metrics, latest_updated_at = surreal_db.get_os_metrics(
        _utc_date(2), _utc_date(0), fields=["sessions_count", "input_tokens"]
    )
    assert latest_updated_at is not None
    assert metrics == [
        {"date": _utc_date(2), "sessions_count": 2, "input_tokens": 30},
        {"date": _utc_date(1), "sessions_count": 0, "input_tokens": 0},
        {"date": _utc_date(0), "sessions_count": 1, "input_tokens": 30},
    ]

    metrics, _ = surreal_db.get_os_metrics(_utc_date(2), _utc_date(0), user_id="bob", fields=["runs_count"])
    assert metrics == [{"date": _utc_date(2), "runs_count": 1}]

    totals, _ = surreal_db.get_os_metrics_totals(
        _utc_date(70), _utc_date(0), fields=["sessions_count", "model_metrics"]
    )
    assert totals == {
        "sessions_count": 4,
        "model_metrics": [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4}],
    }


def test_refresh_os_metrics_versions(surreal_db: SurrealDb, sample_sessions):
    surreal_db.calculate_os_metrics()
    surreal_db._os_metrics_refreshed_at = time.time()
    versions = surreal_db.get_os_metrics_versions(_utc_date(2), _utc_date(0))
    assert versions == {f"daily {_utc_date(days_ago).isoformat()}": 1 for days_ago in [2, 1, 0]}

    previous_updated_at, updated_at, changed = surreal_db.refresh_os_metrics()
    assert previous_updated_at == updated_at and changed is False

    surreal_db.upsert_run(_run_on(_utc_date(0), "alice_run_2", "alice", 40), session_id="alice_today_session")
    _, _, changed = surreal_db.refresh_os_metrics()
    assert changed is True
    assert surreal_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) == {
        **versions,
        f"daily {_utc_date(0).isoformat()}": 2,
    }


def test_lazy_refresh_skipped_when_nothing_new(surreal_db: SurrealDb, sample_sessions):
    surreal_db.calculate_os_metrics()
    time.sleep(1.1)  # leave the second the sessions were written in
    assert surreal_db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert surreal_db._os_metrics_fingerprint is not None

    assert surreal_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert surreal_db._calculate_os_metrics(wait_for_rebuild=True) is not None


def test_lock_os_metrics_refuses_a_second_holder(surreal_db: SurrealDb):
    table = surreal_db._get_table("os_metrics")
    token = lock_os_metrics(surreal_db.client, table, False)
    assert token is not None
    assert lock_os_metrics(surreal_db.client, table, False) is None

    unlock_os_metrics(surreal_db.client, table, token)
    assert lock_os_metrics(surreal_db.client, table, False) is not None


def test_get_os_metrics_versions_incomplete(surreal_db: SurrealDb, sample_sessions):
    surreal_db._os_metrics_refreshed_at = time.time()
    assert surreal_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) is None
