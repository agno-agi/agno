"""Unit tests for the OS Metrics related methods of the InMemoryDb class"""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest

from agno.db.in_memory import InMemoryDb
from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

# The run statuses as the records key them
COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value


@pytest.fixture
def in_memory_db() -> InMemoryDb:
    """Create an InMemoryDb"""
    return InMemoryDb()


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics record is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back"""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _persist(db: InMemoryDb, sessions: List[AgentSession]) -> None:
    """Store each session the way v3 does: the record, then each of its runs"""
    for session in sessions:
        db.upsert_session(session)
        for run_index, run in enumerate(session.runs or []):
            db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _run_metrics(input_tokens: int, output_tokens: int) -> RunMetrics:
    """The token metrics a finished run carries"""
    return RunMetrics(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=input_tokens + output_tokens)


def _agent_run(run_id: str, user_id: str, created_at: int, metrics: RunMetrics, status=RunStatus.completed):
    """A run of agent-1 by the given owner"""
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        user_id=user_id,
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=metrics,
        created_at=created_at,
    )


def _agent_session(session_id: str, user_id: str, created_at: int, runs: List[RunOutput]) -> AgentSession:
    """A session of agent-1 by the given owner"""
    return AgentSession(session_id=session_id, agent_id="agent-1", user_id=user_id, runs=runs, created_at=created_at)


def _records(db: InMemoryDb) -> List[Dict]:
    """Every OS metrics record stored, of every period"""
    return deepcopy(db._os_metrics)


def _stored_rows(db: InMemoryDb) -> Dict[tuple, Dict]:
    """Every daily OS metrics record stored, keyed by (date, user_id)"""
    stored_rows = {}
    for record in _records(db):
        if record["aggregation_period"] == "daily":
            stored_rows[(date.fromisoformat(record["date"]), record["user_id"])] = record
    return stored_rows


@pytest.fixture
def sample_sessions_for_os_metrics() -> List[AgentSession]:
    """Fixture returning the sessions of one past day, plus one of today"""
    base_time = _noon_utc(1)
    today_time = _noon_utc(0)

    # Yesterday: alice's agent session, with a completed run and an error run
    alice_runs = [
        _agent_run("alice_run_completed", "alice", base_time, _run_metrics(100, 50)),
        _agent_run("alice_run_error", "alice", base_time + 60, _run_metrics(10, 0), status=RunStatus.error),
    ]
    alice_agent_session = _agent_session("alice_agent_session", "alice", base_time, alice_runs)

    # Yesterday: bob's agent session
    bob_runs = [_agent_run("bob_run_completed", "bob", base_time + 3600, _run_metrics(200, 100))]
    bob_agent_session = _agent_session("bob_agent_session", "bob", base_time + 3600, bob_runs)

    # Today: one more agent session of alice's
    today_runs = [_agent_run("alice_today_run", "alice", today_time, _run_metrics(1, 1))]
    alice_today_session = _agent_session("alice_today_session", "alice", today_time, today_runs)

    return [alice_agent_session, bob_agent_session, alice_today_session]


def test_calculate_os_metrics(in_memory_db: InMemoryDb, sample_sessions_for_os_metrics):
    """Ensure calculate_os_metrics writes one record per owner for each day"""
    _persist(in_memory_db, sample_sessions_for_os_metrics)

    in_memory_db.calculate_os_metrics()

    yesterday = _utc_date(1)
    today = _utc_date(0)
    stored_rows = _stored_rows(in_memory_db)
    assert set(stored_rows) == {(yesterday, "alice"), (yesterday, "bob"), (today, "alice")}

    alice_row = stored_rows[(yesterday, "alice")]
    assert alice_row["sessions_count"] == 1
    assert alice_row["runs_count"] == 2
    assert alice_row["status_metrics"] == {COMPLETED: 1, ERROR: 1}
    assert alice_row["token_metrics"] == {"input_tokens": 110, "output_tokens": 50, "total_tokens": 160}

    bob_row = stored_rows[(yesterday, "bob")]
    assert bob_row["sessions_count"] == 1
    assert bob_row["runs_count"] == 1
    assert bob_row["token_metrics"] == {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}


def test_get_os_metrics_by_date(in_memory_db: InMemoryDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals the records of each day, with only the fields asked for"""
    _persist(in_memory_db, sample_sessions_for_os_metrics)
    in_memory_db.calculate_os_metrics()

    yesterday = _utc_date(1)
    today = _utc_date(0)
    # Every field: one dict per day, oldest first
    metrics, _ = in_memory_db.get_os_metrics(starting_date=yesterday, ending_date=today)
    assert [m["date"] for m in metrics] == [yesterday, today]
    assert metrics[0]["sessions_count"] == 2
    assert metrics[0]["runs_count"] == 3
    assert metrics[0]["status_metrics"] == {COMPLETED: 2, ERROR: 1}
    assert metrics[0]["token_metrics"] == {"input_tokens": 310, "output_tokens": 150, "total_tokens": 460}

    # Only the fields asked for
    metrics, _ = in_memory_db.get_os_metrics(starting_date=yesterday, ending_date=today, fields=["runs_count"])
    assert metrics == [{"date": yesterday, "runs_count": 3}, {"date": today, "runs_count": 1}]


def test_get_os_metrics_by_user(in_memory_db: InMemoryDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals only the records of the given owner"""
    _persist(in_memory_db, sample_sessions_for_os_metrics)
    in_memory_db.calculate_os_metrics()

    metrics, _ = in_memory_db.get_os_metrics(starting_date=_utc_date(1), ending_date=_utc_date(0), user_id="bob")
    assert [m["date"] for m in metrics] == [_utc_date(1)]
    assert metrics[0]["sessions_count"] == 1
    assert metrics[0]["runs_count"] == 1
    assert metrics[0]["token_metrics"] == {"input_tokens": 200, "output_tokens": 100, "total_tokens": 300}


def test_calculate_os_metrics_after_new_run(in_memory_db: InMemoryDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild counts a run stored since the last one, and changes nothing when there is none"""
    _persist(in_memory_db, sample_sessions_for_os_metrics)
    in_memory_db.calculate_os_metrics()
    records = _records(in_memory_db)

    # Nothing new: the stored records stay as they are
    in_memory_db.calculate_os_metrics()
    assert _records(in_memory_db) == records

    # One more run today
    run = _agent_run("alice_today_run_2", "alice", _noon_utc(0) + 60, _run_metrics(10, 5))
    in_memory_db.upsert_run(run, session_id="alice_today_session", user_id="alice", run_index=1)
    in_memory_db.calculate_os_metrics()

    today_row = _stored_rows(in_memory_db)[(_utc_date(0), "alice")]
    assert today_row["runs_count"] == 2
    assert today_row["token_metrics"] == {"input_tokens": 11, "output_tokens": 6, "total_tokens": 17}


def test_refresh_os_metrics(in_memory_db: InMemoryDb, sample_sessions_for_os_metrics):
    """Ensure refresh_os_metrics reports when the OS metrics were updated before and after, and whether they changed"""
    _persist(in_memory_db, sample_sessions_for_os_metrics)

    previous_updated_at, updated_at, changed = in_memory_db.refresh_os_metrics()
    assert (previous_updated_at, changed) == (None, True)
    assert updated_at is not None

    # Nothing new: no change is reported
    assert in_memory_db.refresh_os_metrics() == (updated_at, updated_at, False)

    # One more run today
    run = _agent_run("alice_today_run_2", "alice", _noon_utc(0) + 60, _run_metrics(10, 5))
    in_memory_db.upsert_run(run, session_id="alice_today_session", user_id="alice", run_index=1)
    previous_updated_at, latest_updated_at, changed = in_memory_db.refresh_os_metrics()
    assert (previous_updated_at, changed) == (updated_at, True)
    assert latest_updated_at >= updated_at


def test_get_os_metrics_state(in_memory_db: InMemoryDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics_state returns when the OS metrics were last written, and the hash of the state"""
    _persist(in_memory_db, sample_sessions_for_os_metrics)
    _, updated_at, _ = in_memory_db.refresh_os_metrics()

    latest_updated_at, state_hash = in_memory_db.get_os_metrics_state()
    assert latest_updated_at == updated_at
    assert state_hash
