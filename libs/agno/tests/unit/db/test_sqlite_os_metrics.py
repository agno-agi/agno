"""Unit tests for the OS Metrics related methods of the SqliteDb and AsyncSqliteDb classes"""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest
from sqlalchemy import select, text, update

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back."""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _run(run_id: str, user_id: str, input_tokens: int, output_tokens: int, created_at: int) -> RunOutput:
    """A completed agent run with the metrics a finished run carries."""
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        user_id=user_id,
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            duration=1.5,
            details={
                "model": [
                    ModelMetrics(
                        id="gpt-5",
                        provider="OpenAI",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                        total_tokens=input_tokens + output_tokens,
                    )
                ]
            },
        ),
        created_at=created_at,
    )


def _session(session_id: str, user_id: str, runs: List[RunOutput], created_at: int) -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id="agent-1",
        user_id=user_id,
        runs=runs,
        created_at=created_at,
        updated_at=created_at,
    )


def _sample_sessions() -> List[AgentSession]:
    """The sessions the tests read.

    Two days back: alice's session with two runs and bob's with one. Seventy days back, in a completed month:
    one session of bob's.
    """
    past_day, old_day = _noon_utc(2), _noon_utc(70)
    return [
        _session(
            "alice_session",
            "alice",
            [
                _run("alice_run_1", "alice", 100, 50, past_day),
                _run("alice_run_2", "alice", 10, 5, past_day + 60),
            ],
            past_day,
        ),
        _session("bob_session", "bob", [_run("bob_run_1", "bob", 200, 100, past_day)], past_day),
        _session("bob_old_session", "bob", [_run("bob_old_run", "bob", 20, 10, old_day)], old_day),
    ]


def _persist(db: SqliteDb, session: AgentSession) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table."""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


async def _apersist(db: AsyncSqliteDb, session: AgentSession) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table."""
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _backdate(db: SqliteDb) -> None:
    """Date every update of the sessions and runs to their creation, so none was updated in the current second."""
    with db.Session() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = db._get_table(table_type)
            sess.execute(update(table).values(updated_at=table.c.created_at))


async def _abackdate(db: AsyncSqliteDb) -> None:
    """Date every update of the sessions and runs to their creation, so none was updated in the current second."""
    async with db.async_session_factory() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = await db._get_table(table_type)
            await sess.execute(update(table).values(updated_at=table.c.created_at))


def _stored_rows(db: SqliteDb, table_type: str) -> Dict[tuple, Dict]:
    """Every row of an OS metrics table, keyed by its aggregation period, date and user."""
    table = db._get_table(table_type, create_table_if_not_found=True)
    with db.Session() as sess:
        result = sess.execute(select(table))
        return {
            (row.aggregation_period, row.date, getattr(row, "user_id", None)): dict(row._mapping)
            for row in result.fetchall()
        }


async def _astored_rows(db: AsyncSqliteDb, table_type: str) -> Dict[tuple, Dict]:
    """Every row of an OS metrics table, keyed by its aggregation period, date and user."""
    table = await db._get_table(table_type, create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table))
        return {
            (row.aggregation_period, row.date, getattr(row, "user_id", None)): dict(row._mapping)
            for row in result.fetchall()
        }


def _numbers(row: Dict) -> tuple:
    """The sessions, runs and total tokens of an OS metrics row."""
    return row["sessions_count"], row["runs_count"], row["total_tokens"]


@pytest.fixture
def sqlite_db(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "test.db"))
    for session in _sample_sessions():
        _persist(db, session)
    _backdate(db)
    return db


@pytest.fixture
async def async_sqlite_db(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "test_async.db"))
    for session in _sample_sessions():
        await _apersist(db, session)
    await _abackdate(db)
    return db


# =============================================================================
# Sync SqliteDb
# =============================================================================


def test_calculate_os_metrics(sqlite_db):
    """Ensure a rebuild stores one row per owner and day, a total row for every day, and the rows of a completed month"""
    sqlite_db.calculate_os_metrics()

    rows = _stored_rows(sqlite_db, "os_metrics")
    assert _numbers(rows[("daily", _utc_date(2), "alice")]) == (1, 2, 165)
    assert _numbers(rows[("daily", _utc_date(2), "bob")]) == (1, 1, 300)
    assert rows[("daily", _utc_date(2), "alice")]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}
    ]

    totals = _stored_rows(sqlite_db, "os_metrics_totals")
    assert _numbers(totals[("daily", _utc_date(2), None)]) == (2, 3, 465)
    assert totals[("daily", _utc_date(2), None)]["completed"] is True
    assert totals[("daily", _utc_date(2), None)]["version"] == 1
    # A day without traffic has a total row of zeros, and today is not completed
    assert _numbers(totals[("daily", _utc_date(1), None)]) == (0, 0, 0)
    assert totals[("daily", _utc_date(0), None)]["completed"] is False
    assert len([key for key in totals if key[0] == "daily"]) == 71

    month_start = _utc_date(70).replace(day=1)
    assert _numbers(rows[("monthly", month_start, "bob")]) == (1, 1, 30)
    assert _numbers(totals[("monthly", month_start, None)]) == (1, 1, 30)


def test_calculate_month_os_metrics_in_batches(sqlite_db, monkeypatch):
    """Ensure a month read a row at a time adds up the rows of all its days"""
    monkeypatch.setattr("agno.db.sqlite.sqlite.OS_METRICS_BATCH_SIZE", 1)
    # Another day of the same month as bob's old session
    days_ago = 71 if _utc_date(70).day > 1 else 69
    _persist(
        sqlite_db,
        _session(
            "bob_older_session", "bob", [_run("bob_older_run", "bob", 2, 1, _noon_utc(days_ago))], _noon_utc(days_ago)
        ),
    )
    _backdate(sqlite_db)
    sqlite_db.calculate_os_metrics()

    month_start = _utc_date(70).replace(day=1)
    assert _numbers(_stored_rows(sqlite_db, "os_metrics")[("monthly", month_start, "bob")]) == (2, 2, 33)
    assert _numbers(_stored_rows(sqlite_db, "os_metrics_totals")[("monthly", month_start, None)]) == (2, 2, 33)


def test_calculate_os_metrics_counts_legacy_runs_and_skips_fork_copies(tmp_path):
    """Ensure a run kept only in the legacy runs column counts once, and a run copied into a forked session not at
    all"""
    db_file = str(tmp_path / "legacy.db")
    db = SqliteDb(db_file=db_file)
    day = _noon_utc(2)
    legacy_session = _session(
        "legacy_session", "carol", [_run("in_both", "carol", 10, 0, day), _run("legacy_only", "carol", 20, 0, day)], day
    )
    db.upsert_session(legacy_session)
    db.upsert_run(legacy_session.runs[0], session_id="legacy_session", user_id="carol", run_index=0)
    copied_run = _run("copied", "carol", 40, 0, day)
    copied_run.forked_from_session_id = "legacy_session"
    _persist(db, _session("copied_session", "carol", [copied_run], day))
    with db.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN runs JSON"))
        sess.execute(
            text("UPDATE agno_sessions SET runs = :runs WHERE session_id = 'legacy_session'"),
            {"runs": json.dumps([run.to_dict() for run in legacy_session.runs])},
        )

    # A new instance, so the sessions table is read with its legacy column
    legacy_db = SqliteDb(db_file=db_file)
    legacy_db.calculate_os_metrics()

    assert _numbers(_stored_rows(legacy_db, "os_metrics")[("daily", _utc_date(2), "carol")]) == (2, 2, 30)


def test_get_os_metrics(sqlite_db):
    """Ensure a read returns the totals of each day, for every owner or one, with only the fields asked for"""
    os_metrics, latest_updated_at = sqlite_db.get_os_metrics(
        _utc_date(3), _utc_date(2), fields=["sessions_count", "runs_count", "status_metrics"]
    )
    assert os_metrics == [
        {"date": _utc_date(3), "sessions_count": 0, "runs_count": 0, "status_metrics": {}},
        {"date": _utc_date(2), "sessions_count": 2, "runs_count": 3, "status_metrics": {"COMPLETED": 3}},
    ]
    assert latest_updated_at is not None

    os_metrics, _ = sqlite_db.get_os_metrics(_utc_date(2), _utc_date(2), user_id="alice")
    assert len(os_metrics) == 1
    assert _numbers(os_metrics[0]) == (1, 2, 165)
    assert os_metrics[0]["duration_buckets"] == {"le_1500": 2}


def test_get_os_metrics_totals(sqlite_db):
    """Ensure the totals of a date range are one record, a completed month read from its month row"""
    totals, latest_updated_at = sqlite_db.get_os_metrics_totals(_utc_date(80), _utc_date(0))

    assert _numbers(totals) == (3, 4, 495)
    assert totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4}]
    assert latest_updated_at is not None


def test_refresh_os_metrics_versions(sqlite_db):
    """Ensure a refresh moves the version of the day it changes, and leaves an unchanged day as it is"""
    previous_updated_at, latest_updated_at, changed = sqlite_db.refresh_os_metrics()
    assert previous_updated_at is None
    assert latest_updated_at is not None
    assert changed is True
    versions = sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    assert versions == {f"daily {_utc_date(1).isoformat()}": 1, f"daily {_utc_date(0).isoformat()}": 1}

    assert sqlite_db.refresh_os_metrics()[2] is False
    sqlite_db.upsert_run(
        _run("bob_run_2", "bob", 1, 2, _noon_utc(0)), session_id="bob_session", user_id="bob", run_index=1
    )
    assert sqlite_db.refresh_os_metrics()[2] is True
    versions = sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    assert versions == {f"daily {_utc_date(1).isoformat()}": 1, f"daily {_utc_date(0).isoformat()}": 2}


def test_lazy_refresh_skipped_when_nothing_new(sqlite_db):
    """Ensure a lazy refresh with no new session or run is skipped, and an explicit one still rebuilds"""
    sqlite_db.calculate_os_metrics()
    # The first refresh after the first build reads from yesterday on, so it reads what no refresh read before
    assert sqlite_db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert sqlite_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert sqlite_db._calculate_os_metrics(wait_for_rebuild=True) is not None


def test_get_os_metrics_versions_incomplete(sqlite_db):
    """Ensure the versions are None while sessions exist and the days are not built up to today"""
    sqlite_db._os_metrics_refreshed_at = time.time()
    assert sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is None

    sqlite_db.calculate_os_metrics()
    assert sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is not None


# =============================================================================
# Async AsyncSqliteDb
# =============================================================================


@pytest.mark.asyncio
async def test_async_calculate_os_metrics(async_sqlite_db):
    """Ensure a rebuild stores one row per owner and day, a total row for every day, and the rows of a completed month"""
    await async_sqlite_db.calculate_os_metrics()

    rows = await _astored_rows(async_sqlite_db, "os_metrics")
    assert _numbers(rows[("daily", _utc_date(2), "alice")]) == (1, 2, 165)
    assert _numbers(rows[("daily", _utc_date(2), "bob")]) == (1, 1, 300)
    assert rows[("daily", _utc_date(2), "alice")]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}
    ]

    totals = await _astored_rows(async_sqlite_db, "os_metrics_totals")
    assert _numbers(totals[("daily", _utc_date(2), None)]) == (2, 3, 465)
    assert totals[("daily", _utc_date(2), None)]["completed"] is True
    assert totals[("daily", _utc_date(2), None)]["version"] == 1
    # A day without traffic has a total row of zeros, and today is not completed
    assert _numbers(totals[("daily", _utc_date(1), None)]) == (0, 0, 0)
    assert totals[("daily", _utc_date(0), None)]["completed"] is False
    assert len([key for key in totals if key[0] == "daily"]) == 71

    month_start = _utc_date(70).replace(day=1)
    assert _numbers(rows[("monthly", month_start, "bob")]) == (1, 1, 30)
    assert _numbers(totals[("monthly", month_start, None)]) == (1, 1, 30)


@pytest.mark.asyncio
async def test_async_calculate_month_os_metrics_in_batches(async_sqlite_db, monkeypatch):
    """Ensure a month read a row at a time adds up the rows of all its days"""
    monkeypatch.setattr("agno.db.sqlite.async_sqlite.OS_METRICS_BATCH_SIZE", 1)
    # Another day of the same month as bob's old session
    days_ago = 71 if _utc_date(70).day > 1 else 69
    await _apersist(
        async_sqlite_db,
        _session(
            "bob_older_session", "bob", [_run("bob_older_run", "bob", 2, 1, _noon_utc(days_ago))], _noon_utc(days_ago)
        ),
    )
    await _abackdate(async_sqlite_db)
    await async_sqlite_db.calculate_os_metrics()

    month_start = _utc_date(70).replace(day=1)
    assert _numbers((await _astored_rows(async_sqlite_db, "os_metrics"))[("monthly", month_start, "bob")]) == (2, 2, 33)
    assert _numbers((await _astored_rows(async_sqlite_db, "os_metrics_totals"))[("monthly", month_start, None)]) == (
        2,
        2,
        33,
    )


@pytest.mark.asyncio
async def test_async_get_os_metrics(async_sqlite_db):
    """Ensure a read returns the totals of each day, for every owner or one, with only the fields asked for"""
    os_metrics, latest_updated_at = await async_sqlite_db.get_os_metrics(
        _utc_date(3), _utc_date(2), fields=["sessions_count", "runs_count", "status_metrics"]
    )
    assert os_metrics == [
        {"date": _utc_date(3), "sessions_count": 0, "runs_count": 0, "status_metrics": {}},
        {"date": _utc_date(2), "sessions_count": 2, "runs_count": 3, "status_metrics": {"COMPLETED": 3}},
    ]
    assert latest_updated_at is not None

    os_metrics, _ = await async_sqlite_db.get_os_metrics(_utc_date(2), _utc_date(2), user_id="alice")
    assert len(os_metrics) == 1
    assert _numbers(os_metrics[0]) == (1, 2, 165)
    assert os_metrics[0]["duration_buckets"] == {"le_1500": 2}


@pytest.mark.asyncio
async def test_async_get_os_metrics_totals(async_sqlite_db):
    """Ensure the totals of a date range are one record, a completed month read from its month row"""
    totals, latest_updated_at = await async_sqlite_db.get_os_metrics_totals(_utc_date(80), _utc_date(0))

    assert _numbers(totals) == (3, 4, 495)
    assert totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4}]
    assert latest_updated_at is not None


@pytest.mark.asyncio
async def test_async_refresh_os_metrics_versions(async_sqlite_db):
    """Ensure a refresh moves the version of the day it changes, and leaves an unchanged day as it is"""
    previous_updated_at, latest_updated_at, changed = await async_sqlite_db.refresh_os_metrics()
    assert previous_updated_at is None
    assert latest_updated_at is not None
    assert changed is True
    versions = await async_sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    assert versions == {f"daily {_utc_date(1).isoformat()}": 1, f"daily {_utc_date(0).isoformat()}": 1}

    assert (await async_sqlite_db.refresh_os_metrics())[2] is False
    await async_sqlite_db.upsert_run(
        _run("bob_run_2", "bob", 1, 2, _noon_utc(0)), session_id="bob_session", user_id="bob", run_index=1
    )
    assert (await async_sqlite_db.refresh_os_metrics())[2] is True
    versions = await async_sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    assert versions == {f"daily {_utc_date(1).isoformat()}": 1, f"daily {_utc_date(0).isoformat()}": 2}


@pytest.mark.asyncio
async def test_async_lazy_refresh_skipped_when_nothing_new(async_sqlite_db):
    """Ensure a lazy refresh with no new session or run is skipped, and an explicit one still rebuilds"""
    await async_sqlite_db.calculate_os_metrics()
    # The first refresh after the first build reads from yesterday on, so it reads what no refresh read before
    assert await async_sqlite_db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert await async_sqlite_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert await async_sqlite_db._calculate_os_metrics(wait_for_rebuild=True) is not None


@pytest.mark.asyncio
async def test_async_get_os_metrics_versions_incomplete(async_sqlite_db):
    """Ensure the versions are None while sessions exist and the days are not built up to today"""
    async_sqlite_db._os_metrics_refreshed_at = time.time()
    assert await async_sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is None

    await async_sqlite_db.calculate_os_metrics()
    assert await async_sqlite_db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is not None
