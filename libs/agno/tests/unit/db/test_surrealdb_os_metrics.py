"""Unit tests for the OS Metrics related methods of the SurrealDb class"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest
from surrealdb import Surreal

from agno.db.surrealdb import SurrealDb
from agno.db.surrealdb.metrics import desurrealize_os_metric
from agno.db.utils import OS_METRICS_STATE_ID
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
    )


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _persist(db: SurrealDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table"""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


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
        metrics=RunMetrics(**tokens, details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI", **tokens)]}),
        created_at=int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp()),
    )


def _session_on(day: date, session_id: str, user_id: str, input_tokens: int = 10) -> AgentSession:
    """An agent session created at midday UTC of the given day, with one completed run"""
    run = _run_on(day, f"{session_id}_run", user_id, input_tokens)
    return AgentSession(
        session_id=session_id,
        agent_id="agent-1",
        user_id=user_id,
        runs=[run],
        created_at=run.created_at,
    )


def _all_rows(db: SurrealDb) -> List[Dict]:
    """Every OS metrics row in the table, in the shape calculate_date_os_metrics writes"""
    table = db._get_table("os_metrics")
    return [desurrealize_os_metric(record) for record in db._query(f"SELECT * FROM {table}", {}, dict)]


def _stored_rows(db: SurrealDb) -> Dict[tuple, Dict]:
    """Every OS metrics row of an owner in the table, keyed by (date, user_id)"""
    return {(row["date"], row["user_id"]): row for row in _all_rows(db) if row["aggregation_period"] == "daily"}


@pytest.fixture
def sample_sessions_for_os_metrics(surreal_db: SurrealDb) -> List[AgentSession]:
    """Store one session each for alice and bob yesterday, and one for alice today"""
    sessions = [
        _session_on(_utc_date(1), "alice_session", "alice", input_tokens=10),
        _session_on(_utc_date(1), "bob_session", "bob", input_tokens=20),
        _session_on(_utc_date(0), "alice_today_session", "alice", input_tokens=30),
    ]
    for session in sessions:
        _persist(surreal_db, session)
    return sessions


def test_calculate_os_metrics(surreal_db: SurrealDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild stores the rows of each day with the numbers of each owner"""
    assert surreal_db.calculate_os_metrics()

    rows = _stored_rows(surreal_db)
    assert {key: (row["sessions_count"], row["runs_count"]) for key, row in rows.items()} == {
        (_utc_date(1), "alice"): (1, 1),
        (_utc_date(1), "bob"): (1, 1),
        (_utc_date(0), "alice"): (1, 1),
    }
    alice_tokens = rows[(_utc_date(1), "alice")]["token_metrics"]
    assert alice_tokens == {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    bob_tokens = rows[(_utc_date(1), "bob")]["token_metrics"]
    assert bob_tokens == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}


def test_get_os_metrics_by_date(surreal_db: SurrealDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals the rows of each day, with only the fields asked for"""
    surreal_db.calculate_os_metrics()
    yesterday, today = _utc_date(1), _utc_date(0)

    metrics, latest_updated_at = surreal_db.get_os_metrics(starting_date=yesterday, ending_date=today)
    assert latest_updated_at is not None
    assert [m["date"] for m in metrics] == [yesterday, today]
    assert (metrics[0]["sessions_count"], metrics[0]["runs_count"]) == (2, 2)
    assert metrics[0]["token_metrics"] == {"input_tokens": 30, "output_tokens": 10, "total_tokens": 40}
    assert metrics[1]["token_metrics"] == {"input_tokens": 30, "output_tokens": 5, "total_tokens": 35}

    metrics, _ = surreal_db.get_os_metrics(yesterday, yesterday, fields=["sessions_count", "runs_count"])
    assert metrics == [{"date": yesterday, "sessions_count": 2, "runs_count": 2}]


def test_get_os_metrics_by_user(surreal_db: SurrealDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals only the rows of the given owner"""
    surreal_db.calculate_os_metrics()

    metrics, _ = surreal_db.get_os_metrics(starting_date=_utc_date(1), ending_date=_utc_date(0), user_id="bob")
    assert [m["date"] for m in metrics] == [_utc_date(1)]
    assert (metrics[0]["sessions_count"], metrics[0]["runs_count"]) == (1, 1)
    assert metrics[0]["token_metrics"] == {"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}


def test_calculate_os_metrics_after_new_run(surreal_db: SurrealDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild with nothing new changes no row, and one after a new run changes the numbers"""
    surreal_db.calculate_os_metrics()
    rows = _all_rows(surreal_db)

    surreal_db.calculate_os_metrics()
    assert _all_rows(surreal_db) == rows

    run = _run_on(_utc_date(1), "alice_run_2", "alice", input_tokens=40)
    surreal_db.upsert_run(run, session_id="alice_session", user_id="alice", run_index=1)
    surreal_db.calculate_os_metrics()

    alice_row = _stored_rows(surreal_db)[(_utc_date(1), "alice")]
    assert (alice_row["sessions_count"], alice_row["runs_count"]) == (1, 2)
    assert alice_row["token_metrics"] == {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}


def test_refresh_os_metrics(surreal_db: SurrealDb, sample_sessions_for_os_metrics):
    """Ensure refresh_os_metrics reports when the rows were updated before and after, and whether any changed"""
    previous_updated_at, updated_at, changed = surreal_db.refresh_os_metrics()
    assert previous_updated_at is None
    assert updated_at is not None and changed is True

    assert surreal_db.refresh_os_metrics() == (updated_at, updated_at, False)


def test_get_os_metrics_state(surreal_db: SurrealDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics_state returns when the rows were last written and the hash of the state"""
    surreal_db.calculate_os_metrics()

    rows = [row for row in _all_rows(surreal_db) if row["aggregation_period"] != OS_METRICS_STATE_ID]
    updated_at, state_hash = surreal_db.get_os_metrics_state()
    assert updated_at >= max(row["updated_at"] for row in rows)
    assert state_hash
