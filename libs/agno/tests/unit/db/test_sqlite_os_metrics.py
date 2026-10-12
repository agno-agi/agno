"""Unit tests for the OS Metrics related methods of the SqliteDb and AsyncSqliteDb classes"""

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest
from sqlalchemy import select

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back"""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _run(run_id: str, user_id: str, input_tokens: int, output_tokens: int, created_at: int) -> RunOutput:
    """A completed agent run with the metrics a finished run carries"""
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
    """Two days back: alice's session with two runs and bob's with one. Three days back: one session of bob's"""
    past_day, three_days_back = _noon_utc(2), _noon_utc(3)
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
        _session("bob_old_session", "bob", [_run("bob_old_run", "bob", 20, 10, three_days_back)], three_days_back),
    ]


def _persist(db: SqliteDb, session: AgentSession) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table"""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


async def _apersist(db: AsyncSqliteDb, session: AgentSession) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table"""
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _stored_rows(db: SqliteDb) -> Dict[tuple, Dict]:
    """Every OS metrics row of a day in the table, keyed by (date, aggregation_period, user_id)"""
    table = db._get_table("os_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        result = sess.execute(select(table).where(table.c.aggregation_period.in_(["daily", "daily_total"])))
        return {(row.date, row.aggregation_period, row.user_id): dict(row._mapping) for row in result.fetchall()}


async def _astored_rows(db: AsyncSqliteDb) -> Dict[tuple, Dict]:
    """Every OS metrics row of a day in the table, keyed by (date, aggregation_period, user_id)"""
    table = await db._get_table("os_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table).where(table.c.aggregation_period.in_(["daily", "daily_total"])))
        return {(row.date, row.aggregation_period, row.user_id): dict(row._mapping) for row in result.fetchall()}


def _numbers(row: Dict) -> tuple:
    """The sessions, runs and total tokens of an OS metrics row"""
    return row["sessions_count"], row["runs_count"], row["token_metrics"]["total_tokens"]


@pytest.fixture
def sqlite_db(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "test.db"))
    for session in _sample_sessions():
        _persist(db, session)
    return db


@pytest.fixture
async def async_sqlite_db(tmp_path):
    db = AsyncSqliteDb(db_file=str(tmp_path / "test_async.db"))
    for session in _sample_sessions():
        await _apersist(db, session)
    return db


# -- SqliteDb --


def test_calculate_os_metrics(sqlite_db):
    """Ensure a rebuild stores one row per owner and one total row for a day"""
    sqlite_db.calculate_os_metrics()

    stored_rows = _stored_rows(sqlite_db)
    assert _numbers(stored_rows[(_utc_date(2), "daily", "alice")]) == (1, 2, 165)
    assert _numbers(stored_rows[(_utc_date(2), "daily", "bob")]) == (1, 1, 300)
    assert _numbers(stored_rows[(_utc_date(2), "daily_total", "")]) == (2, 3, 465)
    assert _numbers(stored_rows[(_utc_date(3), "daily", "bob")]) == (1, 1, 30)


def test_get_os_metrics_by_date(sqlite_db):
    """Ensure a read returns the totals of each day of the date range, with only the fields asked for"""
    os_metrics, latest_updated_at = sqlite_db.get_os_metrics(
        _utc_date(3), _utc_date(2), fields=["sessions_count", "runs_count"]
    )

    assert sorted(os_metrics, key=lambda day: day["date"]) == [
        {"date": _utc_date(3), "sessions_count": 1, "runs_count": 1},
        {"date": _utc_date(2), "sessions_count": 2, "runs_count": 3},
    ]
    assert latest_updated_at is not None


def test_get_os_metrics_by_user(sqlite_db):
    """Ensure a read for one user returns only that user's numbers"""
    os_metrics, _ = sqlite_db.get_os_metrics(_utc_date(2), _utc_date(2), user_id="alice")

    assert len(os_metrics) == 1
    assert _numbers(os_metrics[0]) == (1, 2, 165)


def test_calculate_os_metrics_after_new_run(sqlite_db):
    """Ensure a second rebuild counts a run stored after the first, and changes nothing when there is none"""
    sqlite_db.calculate_os_metrics()
    sqlite_db.upsert_run(
        _run("bob_run_2", "bob", 1, 2, _noon_utc(0)), session_id="bob_session", user_id="bob", run_index=1
    )

    sqlite_db.calculate_os_metrics()
    stored_rows = _stored_rows(sqlite_db)
    assert _numbers(stored_rows[(_utc_date(0), "daily", "bob")]) == (0, 1, 3)
    assert _numbers(stored_rows[(_utc_date(2), "daily_total", "")]) == (2, 3, 465)

    sqlite_db.calculate_os_metrics()
    assert _stored_rows(sqlite_db) == stored_rows


def test_refresh_os_metrics(sqlite_db):
    """Ensure a refresh reports when the rows were last updated before and after it, and whether any changed"""
    previous_updated_at, latest_updated_at, changed = sqlite_db.refresh_os_metrics()
    assert previous_updated_at is None
    assert latest_updated_at is not None
    assert changed is True

    assert sqlite_db.refresh_os_metrics() == (latest_updated_at, latest_updated_at, False)


def test_get_os_metrics_totals_and_state(sqlite_db):
    """Ensure the totals of a date range are one record, and the state row holds the hash of the state"""
    totals, latest_updated_at = sqlite_db.get_os_metrics_totals(_utc_date(3), _utc_date(2))

    assert _numbers(totals) == (3, 4, 495)
    updated_at, state_hash = sqlite_db.get_os_metrics_state()
    assert updated_at >= latest_updated_at
    assert state_hash


# -- AsyncSqliteDb --


@pytest.mark.asyncio
async def test_async_calculate_os_metrics(async_sqlite_db):
    """Ensure a rebuild stores one row per owner and one total row for a day"""
    await async_sqlite_db.calculate_os_metrics()

    stored_rows = await _astored_rows(async_sqlite_db)
    assert _numbers(stored_rows[(_utc_date(2), "daily", "alice")]) == (1, 2, 165)
    assert _numbers(stored_rows[(_utc_date(2), "daily", "bob")]) == (1, 1, 300)
    assert _numbers(stored_rows[(_utc_date(2), "daily_total", "")]) == (2, 3, 465)
    assert _numbers(stored_rows[(_utc_date(3), "daily", "bob")]) == (1, 1, 30)


@pytest.mark.asyncio
async def test_async_get_os_metrics_by_date(async_sqlite_db):
    """Ensure a read returns the totals of each day of the date range, with only the fields asked for"""
    os_metrics, latest_updated_at = await async_sqlite_db.get_os_metrics(
        _utc_date(3), _utc_date(2), fields=["sessions_count", "runs_count"]
    )

    assert sorted(os_metrics, key=lambda day: day["date"]) == [
        {"date": _utc_date(3), "sessions_count": 1, "runs_count": 1},
        {"date": _utc_date(2), "sessions_count": 2, "runs_count": 3},
    ]
    assert latest_updated_at is not None


@pytest.mark.asyncio
async def test_async_get_os_metrics_by_user(async_sqlite_db):
    """Ensure a read for one user returns only that user's numbers"""
    os_metrics, _ = await async_sqlite_db.get_os_metrics(_utc_date(2), _utc_date(2), user_id="alice")

    assert len(os_metrics) == 1
    assert _numbers(os_metrics[0]) == (1, 2, 165)


@pytest.mark.asyncio
async def test_async_calculate_os_metrics_after_new_run(async_sqlite_db):
    """Ensure a second rebuild counts a run stored after the first, and changes nothing when there is none"""
    await async_sqlite_db.calculate_os_metrics()
    await async_sqlite_db.upsert_run(
        _run("bob_run_2", "bob", 1, 2, _noon_utc(0)), session_id="bob_session", user_id="bob", run_index=1
    )

    await async_sqlite_db.calculate_os_metrics()
    stored_rows = await _astored_rows(async_sqlite_db)
    assert _numbers(stored_rows[(_utc_date(0), "daily", "bob")]) == (0, 1, 3)
    assert _numbers(stored_rows[(_utc_date(2), "daily_total", "")]) == (2, 3, 465)

    await async_sqlite_db.calculate_os_metrics()
    assert await _astored_rows(async_sqlite_db) == stored_rows


@pytest.mark.asyncio
async def test_async_refresh_os_metrics(async_sqlite_db):
    """Ensure a refresh reports when the rows were last updated before and after it, and whether any changed"""
    previous_updated_at, latest_updated_at, changed = await async_sqlite_db.refresh_os_metrics()
    assert previous_updated_at is None
    assert latest_updated_at is not None
    assert changed is True

    assert await async_sqlite_db.refresh_os_metrics() == (latest_updated_at, latest_updated_at, False)


@pytest.mark.asyncio
async def test_async_get_os_metrics_totals_and_state(async_sqlite_db):
    """Ensure the totals of a date range are one record, and the state row holds the hash of the state"""
    totals, latest_updated_at = await async_sqlite_db.get_os_metrics_totals(_utc_date(3), _utc_date(2))

    assert _numbers(totals) == (3, 4, 495)
    updated_at, state_hash = await async_sqlite_db.get_os_metrics_state()
    assert updated_at >= latest_updated_at
    assert state_hash
