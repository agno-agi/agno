"""Unit tests for InMemoryDb OS metrics methods."""

import time
import types
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(day: date) -> int:
    """Midday UTC of the given day"""
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _agent_run(run_id: str, created_at: int, input_tokens: int, status=RunStatus.completed) -> RunOutput:
    """A run of agent-1"""
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(input_tokens=input_tokens, output_tokens=10, total_tokens=input_tokens + 10),
        created_at=created_at,
    )


def _persist(db: InMemoryDb, session_id: str, user_id: str, day: date, runs: List[RunOutput]) -> None:
    """Store an agent-1 session created on the given day, then each of its runs"""
    session = AgentSession(
        session_id=session_id, agent_id="agent-1", user_id=user_id, runs=runs, created_at=_noon_utc(day)
    )
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run, session_id=session_id, user_id=user_id, run_index=run_index)


def _rows(rows: List[Dict]) -> Dict[tuple, Dict]:
    """The stored rows of a table, keyed by period, date and owner"""
    return {(row["aggregation_period"], row["date"].isoformat(), row.get("user_id")): row for row in rows}


@pytest.fixture
def db_with_sessions():
    """Yesterday: alice with a completed and an errored run, bob with one run. Today: one run of alice's."""
    db = InMemoryDb()
    yesterday = _utc_date(1)
    _persist(
        db,
        "alice_session",
        "alice",
        yesterday,
        [
            _agent_run("alice_run", _noon_utc(yesterday), 100),
            _agent_run("alice_error_run", _noon_utc(yesterday) + 60, 20, status=RunStatus.error),
        ],
    )
    _persist(db, "bob_session", "bob", yesterday, [_agent_run("bob_run", _noon_utc(yesterday) + 120, 200)])
    _persist(db, "alice_today", "alice", _utc_date(0), [_agent_run("today_run", _noon_utc(_utc_date(0)), 1)])
    return db


class TestCalculateOsMetrics:
    def test_writes_rows_and_totals(self, db_with_sessions):
        db_with_sessions.calculate_os_metrics()

        yesterday = _utc_date(1).isoformat()
        today = _utc_date(0).isoformat()
        rows = _rows(db_with_sessions._os_metrics)
        assert set(rows) == {("daily", yesterday, "alice"), ("daily", yesterday, "bob"), ("daily", today, "alice")}
        alice_row = rows[("daily", yesterday, "alice")]
        assert (alice_row["component_type"], alice_row["component_id"], alice_row["parent_component_id"]) == (
            "agent",
            "agent-1",
            "",
        )
        assert alice_row["sessions_count"] == 1
        assert alice_row["runs_count"] == 2
        assert alice_row["status_metrics"] == {COMPLETED: 1, ERROR: 1}
        assert alice_row["input_tokens"] == 120

        totals = _rows(db_with_sessions._os_metrics_totals)
        assert set(totals) == {("daily", yesterday, None), ("daily", today, None)}
        assert totals[("daily", yesterday, None)]["runs_count"] == 3
        assert totals[("daily", yesterday, None)]["input_tokens"] == 320
        assert [row["version"] for row in totals.values()] == [1, 1]
        assert [row["completed"] for row in totals.values()] == [False, False]

    def test_completed_month_gets_month_rows(self):
        db = InMemoryDb()
        month_start = (_utc_date(0).replace(day=1) - timedelta(days=32)).replace(day=1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        _persist(db, "first_session", "alice", month_start, [_agent_run("first_run", _noon_utc(month_start), 100)])
        _persist(db, "last_session", "alice", month_end, [_agent_run("last_run", _noon_utc(month_end), 50)])

        db.calculate_os_metrics()

        month_row = _rows(db._os_metrics)[("monthly", month_start.isoformat(), "alice")]
        assert (month_row["sessions_count"], month_row["runs_count"], month_row["input_tokens"]) == (2, 2, 150)
        month_totals = _rows(db._os_metrics_totals)[("monthly", month_start.isoformat(), None)]
        assert (month_totals["runs_count"], month_totals["completed"], month_totals["version"]) == (2, True, 1)

        totals, _ = db.get_os_metrics_totals(starting_date=month_start, ending_date=month_end, user_id="alice")
        assert (totals["sessions_count"], totals["runs_count"], totals["input_tokens"]) == (2, 2, 150)


class TestGetOsMetrics:
    def test_reads_every_owner_and_one_owner(self, db_with_sessions):
        db_with_sessions.calculate_os_metrics()

        yesterday = _utc_date(1)
        today = _utc_date(0)
        metrics, updated_at = db_with_sessions.get_os_metrics(
            starting_date=yesterday, ending_date=today, fields=["runs_count", "status_metrics"]
        )
        assert metrics == [
            {"date": yesterday, "runs_count": 3, "status_metrics": {COMPLETED: 2, ERROR: 1}},
            {"date": today, "runs_count": 1, "status_metrics": {COMPLETED: 1}},
        ]
        assert updated_at is not None

        metrics, _ = db_with_sessions.get_os_metrics(starting_date=yesterday, ending_date=today, user_id="bob")
        assert [(m["date"], m["runs_count"], m["input_tokens"]) for m in metrics] == [(yesterday, 1, 200)]

        totals, _ = db_with_sessions.get_os_metrics_totals(starting_date=yesterday, ending_date=today)
        assert (totals["runs_count"], totals["status_metrics"]) == (4, {COMPLETED: 3, ERROR: 1})


class TestRefreshOsMetrics:
    def test_reports_changes_and_moves_versions(self, db_with_sessions):
        assert db_with_sessions.refresh_os_metrics()[2] is True
        versions = db_with_sessions.get_os_metrics_versions(_utc_date(1), _utc_date(0))
        assert versions == {f"daily {_utc_date(1).isoformat()}": 1, f"daily {_utc_date(0).isoformat()}": 1}

        _, _, changed = db_with_sessions.refresh_os_metrics()
        assert changed is False
        assert db_with_sessions.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == versions

        db_with_sessions.upsert_run(
            _agent_run("today_run_2", _noon_utc(_utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice"
        )
        _, _, changed = db_with_sessions.refresh_os_metrics()
        assert changed is True
        assert db_with_sessions.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == {
            f"daily {_utc_date(1).isoformat()}": 1,
            f"daily {_utc_date(0).isoformat()}": 2,
        }

    def test_versions_are_none_while_incomplete(self, db_with_sessions):
        # No lazy refresh before the read
        db_with_sessions._os_metrics_refreshed_at = time.time()
        assert db_with_sessions.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is None


class TestLazyRefresh:
    def test_skipped_with_nothing_new(self, db_with_sessions, monkeypatch):
        from agno.db.in_memory import in_memory_db as in_memory_db_module

        # A clock past the second the rows were written in, so the fingerprint is trusted
        later = time.time() + 5
        monkeypatch.setattr(in_memory_db_module, "time", types.SimpleNamespace(time=lambda: later, sleep=time.sleep))

        assert db_with_sessions._calculate_os_metrics(wait_for_rebuild=True) is not None
        assert db_with_sessions._calculate_os_metrics(wait_for_rebuild=False) is None

        db_with_sessions.upsert_run(
            _agent_run("today_run_2", _noon_utc(_utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice"
        )
        assert db_with_sessions._calculate_os_metrics(wait_for_rebuild=False) is not None

    def test_skipped_while_another_rebuild_holds_the_lock(self, db_with_sessions):
        token = db_with_sessions._lock_os_metrics(wait_for_rebuild=False)
        assert token is not None

        assert db_with_sessions._calculate_os_metrics(wait_for_rebuild=False) is None
        assert db_with_sessions._os_metrics_refreshed_at == 0.0

        db_with_sessions._unlock_os_metrics(token)
        assert db_with_sessions._calculate_os_metrics(wait_for_rebuild=False) is not None
