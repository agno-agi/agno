"""Unit tests for the component metrics related methods of the SqliteDb and AsyncSqliteDb classes."""

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import pytest
from sqlalchemy import create_engine, select, text, update

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.db.utils import METRICS_LOCK_SECONDS, METRICS_REFRESH_ID, METRICS_STOPPED_ERROR
from agno.metrics import ModelMetrics, RunMetrics, ToolCallMetrics
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back."""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day a component metrics row is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _run(
    run_id: str,
    user_id: Optional[str],
    input_tokens: int,
    output_tokens: int,
    created_at: int,
    agent_id: str = "agent-1",
    status: RunStatus = RunStatus.completed,
    cache_read_tokens: int = 0,
    parent_run_id: Optional[str] = None,
) -> RunOutput:
    """An agent run with the metrics a finished run carries."""
    return RunOutput(
        run_id=run_id,
        agent_id=agent_id,
        user_id=user_id,
        parent_run_id=parent_run_id,
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cache_read_tokens=cache_read_tokens,
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


def _session(session_id: str, user_id: Optional[str], runs: List[RunOutput], created_at: int) -> AgentSession:
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


def _persist(db: SqliteDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table."""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


async def _apersist(db: AsyncSqliteDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table."""
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _backdate(db: SqliteDb) -> None:
    """Date every update of the sessions and runs to their creation, so none was updated in the current second."""
    # Looked up first: a lookup inside the scoped session would end its transaction
    tables = [db._get_table(table_type) for table_type in ["sessions", "runs"]]
    with db.Session() as sess, sess.begin():
        for table in tables:
            sess.execute(update(table).values(updated_at=table.c.created_at))


async def _abackdate(db: AsyncSqliteDb) -> None:
    """Date every update of the sessions and runs to their creation, so none was updated in the current second."""
    async with db.async_session_factory() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = await db._get_table(table_type)
            await sess.execute(update(table).values(updated_at=table.c.created_at))


def _stored_rows(db: SqliteDb) -> Dict[tuple, Dict]:
    """Every row of agno_component_metrics, keyed by date, user, component type and component id."""
    table = db._get_table("component_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in sess.execute(select(table)).fetchall()
        }


async def _astored_rows(db: AsyncSqliteDb) -> Dict[tuple, Dict]:
    """Every row of agno_component_metrics, keyed by date, user, component type and component id."""
    table = await db._get_table("component_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in (await sess.execute(select(table))).fetchall()
        }


def _stored_aggregate_metrics_rows(db: SqliteDb) -> Dict[tuple, Dict]:
    """Every day and month row of agno_aggregate_metrics, keyed by (aggregation_period, date, user_id)."""
    table = db._get_table("aggregate_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.aggregation_period, row.date, row.user_id): dict(row._mapping)
            for row in sess.execute(select(table)).fetchall()
        }


async def _astored_aggregate_metrics_rows(db: AsyncSqliteDb) -> Dict[tuple, Dict]:
    """Every day and month row of agno_aggregate_metrics, keyed by (aggregation_period, date, user_id)."""
    table = await db._get_table("aggregate_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        return {
            (row.aggregation_period, row.date, row.user_id): dict(row._mapping)
            for row in (await sess.execute(select(table))).fetchall()
        }


def _numbers(row: Dict) -> tuple:
    """The sessions, runs and total tokens of a component metrics row."""
    return row["sessions_count"], row["runs_count"], row["total_tokens"]


def _aggregate_metrics_numbers(row: Dict) -> tuple:
    """The sessions, runs and total tokens of an aggregate metrics row."""
    return (
        row["agent_sessions_count"] + row["team_sessions_count"] + row["workflow_sessions_count"],
        row["agent_runs_count"] + row["team_runs_count"] + row["workflow_runs_count"],
        row["total_tokens"],
    )


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


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column(tmp_path):
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
    # Not yet migrated to v3.0.0, so the legacy runs are read
    db.upsert_schema_version(db.session_table_name, "2.5.0")

    # A new instance, so the sessions table is read with its legacy column
    legacy_db = SqliteDb(db_file=db_file)
    legacy_db.calculate_metrics()

    assert _numbers(_stored_rows(legacy_db)[(_utc_date(2), "carol", "agent", "agent-1")]) == (2, 2, 30)


def test_calculate_metrics_counts_tool_calls(tmp_path):
    """Ensure each tool call counts in tool_metrics, and one a forked run copied or the user rejected does not"""
    db = SqliteDb(db_file=str(tmp_path / "tools.db"))
    day = _noon_utc(2)
    tool_run = _run("tool_run", "carol", 10, 0, day)
    tool_run.tools = [
        ToolExecution(
            tool_call_id="call-1",
            tool_name="search",
            toolkit="web",
            tool_args={"query": "agno"},
            result="found",
            metrics=ToolCallMetrics(duration=0.2),
        ),
        ToolExecution(tool_call_id="call-2", tool_name="search", toolkit="web", tool_call_error=True, confirmed=False),
    ]
    forked_run = _run("forked_run", "carol", 10, 0, day + 60)
    forked_run.tools = [
        ToolExecution(tool_call_id="call-1", tool_name="search", toolkit="web", metrics=ToolCallMetrics(duration=0.2)),
        ToolExecution(tool_call_id="call-3", tool_name="search", toolkit="web", metrics=ToolCallMetrics(duration=0.4)),
    ]
    forked_run.messages = [Message(role="tool", tool_call_id="call-1"), Message(role="tool", tool_call_id="call-3")]
    forked_run.forked_from_message_index = 1
    # A fork of the fork copies both calls, and the call the first fork made still counts on it
    fork_of_fork = _run("fork_of_fork", "carol", 10, 0, day + 120)
    fork_of_fork.tools = forked_run.tools
    fork_of_fork.messages = forked_run.messages
    fork_of_fork.forked_from_message_index = 2
    _persist(db, _session("tool_session", "carol", [tool_run, forked_run, fork_of_fork], day))
    _backdate(db)
    db.calculate_metrics()

    tool_metrics = {
        "web": {
            "search": {
                "count": 2,
                "failed_count": 0,
                "total_ms": 600,
                "max_ms": 400,
                "buckets": {"le_200": 1, "le_400": 1},
            }
        }
    }
    assert _stored_rows(db)[(_utc_date(2), "carol", "agent", "agent-1")]["tool_metrics"] == tool_metrics
    totals, _ = db.get_metrics_totals(_utc_date(2), _utc_date(2), user_id="carol", fields=["tool_metrics"])
    assert totals["tool_metrics"] == tool_metrics


def test_get_component_metrics(sqlite_db):
    """Ensure a read returns the totals of each day, for every owner or one, with only the fields asked for"""
    sqlite_db.calculate_metrics()
    component_metrics, latest_updated_at = sqlite_db.get_component_metrics(
        _utc_date(2), _utc_date(1), fields=["sessions_count", "root_runs_count", "status_metrics"]
    )
    assert component_metrics == [
        {"date": _utc_date(2), "sessions_count": 2, "root_runs_count": 3, "status_metrics": {"COMPLETED": 3}},
        {"date": _utc_date(1), "sessions_count": 0, "root_runs_count": 0, "status_metrics": {}},
    ]
    assert latest_updated_at is not None

    component_metrics, _ = sqlite_db.get_component_metrics(_utc_date(2), _utc_date(2), user_id="alice")
    assert len(component_metrics) == 1
    assert component_metrics[0]["sessions_count"] == 1
    assert component_metrics[0]["total_tokens"] == 165
    assert component_metrics[0]["duration_buckets"] == {"le_1500": 2}
    assert component_metrics[0]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2, "cost": None}
    ]


def test_calculate_metrics_rebuilds_a_reopened_day(sqlite_db):
    """Ensure a run saved on a completed day reopens the day, and the next calculation counts it"""
    sqlite_db.calculate_metrics()
    version = _stored_aggregate_metrics_rows(sqlite_db)[("daily", _utc_date(2), "")]["version"]

    sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    reopened = _stored_aggregate_metrics_rows(sqlite_db)[("daily", _utc_date(2), "")]
    assert (reopened["completed"], reopened["version"]) == (False, version + 1)

    _backdate(sqlite_db)
    sqlite_db.calculate_metrics()
    rebuilt = _stored_aggregate_metrics_rows(sqlite_db)[("daily", _utc_date(2), "")]
    assert rebuilt["completed"] is True
    assert _aggregate_metrics_numbers(rebuilt) == (2, 4, 467)


def test_session_save_reopens_the_day_the_session_is_stored_on(sqlite_db):
    """Ensure a session save reopens its day when the session is new, and not otherwise"""
    sqlite_db.calculate_metrics()
    alice_session = _sample_sessions()[0]
    sqlite_db.upsert_session(alice_session)
    assert _stored_aggregate_metrics_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is True

    sqlite_db.upsert_sessions([_session("new_session", "carol", [], _noon_utc(2))])
    assert _stored_aggregate_metrics_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is False


def _set_refresh_row(db: SqliteDb, **values) -> None:
    """Change the row of the metrics refreshes table, as another process would."""
    refreshes_table = db._get_table("metrics_refreshes", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        sess.execute(update(refreshes_table).where(refreshes_table.c.id == METRICS_REFRESH_ID).values(**values))


def test_claim_metrics_refresh_returns_while_another_process_writes_a_day(sqlite_db):
    """Ensure a claim returns None, instead of raising, while the transaction of another process's day keeps the
    database locked"""
    refreshes_table = sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert sqlite_db._claim_metrics_refresh(refreshes_table, "other_process") is not None
    # Another process, which waits a moment for the database instead of SQLite's default 5 s
    second_db = SqliteDb(db_engine=create_engine(sqlite_db.db_engine.url, connect_args={"timeout": 0.1}))

    with sqlite_db.db_engine.connect() as conn, conn.begin():
        assert sqlite_db._heartbeat_metrics_refresh(conn, refreshes_table, "other_process")
        assert second_db._claim_metrics_refresh(refreshes_table, "second_process") is None


def test_calculate_metrics_takes_over_a_lock_that_went_stale(sqlite_db):
    """Ensure a calculation returns None while another worker holds the refresh, and a lock whose heartbeat went stale
    reads as failed and is taken over by the next calculation"""
    refreshes_table = sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    sqlite_db._claim_metrics_refresh(refreshes_table, "other-worker")
    assert sqlite_db.calculate_metrics() is None
    _set_refresh_row(sqlite_db, locked_at=int(time.time()) - METRICS_LOCK_SECONDS)
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert sqlite_db.calculate_metrics()
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)
    assert status["finished_at"] is not None


def test_calculate_date_metrics_writes_nothing_after_losing_the_lock(sqlite_db, monkeypatch):
    """Ensure a calculation whose refresh another process took over writes nothing more"""
    refreshes_table = sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)

    def _take_over(self, sess, table, worker_id):
        sess.execute(update(table).where(table.c.id == METRICS_REFRESH_ID).values(locked_by="other-worker"))
        return False

    monkeypatch.setattr(SqliteDb, "_heartbeat_metrics_refresh", _take_over)
    assert sqlite_db.calculate_metrics() is None
    assert _stored_rows(sqlite_db) == {}
    assert sqlite_db._claim_metrics_refresh(refreshes_table, "third-worker") is None


# =============================================================================
# Async AsyncSqliteDb
# =============================================================================


def _save_today_run(db: SqliteDb, run_id: str) -> None:
    """Save one more run of bob's today, updated before the current second."""
    db.upsert_run(_run(run_id, "bob", 1, 2, _noon_utc(0)), session_id="bob_session", user_id="bob")
    _backdate(db)


def test_calculate_metrics_dates_releases_the_lock_when_stopped(sqlite_db):
    """Ensure a calculation told to stop releases the lock: a first one as failed, a later one as the last completed
    one left it"""
    assert sqlite_db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert sqlite_db.calculate_metrics()

    _save_today_run(sqlite_db, "today_run_1")
    assert sqlite_db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)


@pytest.mark.asyncio
async def test_async_get_component_metrics_and_totals(async_sqlite_db):
    """Ensure a read returns the totals of each day and of a date range, for every owner or one"""
    await async_sqlite_db.calculate_metrics()
    component_metrics, latest_updated_at = await async_sqlite_db.get_component_metrics(
        _utc_date(2), _utc_date(1), fields=["sessions_count", "root_runs_count", "status_metrics"]
    )
    assert component_metrics == [
        {"date": _utc_date(2), "sessions_count": 2, "root_runs_count": 3, "status_metrics": {"COMPLETED": 3}},
        {"date": _utc_date(1), "sessions_count": 0, "root_runs_count": 0, "status_metrics": {}},
    ]
    assert latest_updated_at is not None

    component_metrics, _ = await async_sqlite_db.get_component_metrics(_utc_date(2), _utc_date(2), user_id="alice")
    assert component_metrics[0]["duration_buckets"] == {"le_1500": 2}

    totals, _ = await async_sqlite_db.get_metrics_totals(_utc_date(80), _utc_date(0))
    assert (totals["sessions_count"], totals["root_runs_count"], totals["total_tokens"]) == (3, 4, 495)
    assert totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4, "cost": None}]


@pytest.mark.asyncio
async def test_async_saves_reopen_a_closed_day_and_deletes_do_not(async_sqlite_db):
    """Ensure a run save and a new session reopen a closed day, and a delete or an unchanged session save does not"""
    await async_sqlite_db.calculate_metrics()
    await async_sqlite_db.delete_session("bob_session")
    await async_sqlite_db.upsert_session(_sample_sessions()[0])
    assert (await _astored_aggregate_metrics_rows(async_sqlite_db))[("daily", _utc_date(2), "")]["completed"] is True

    await async_sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    reopened = (await _astored_aggregate_metrics_rows(async_sqlite_db))[("daily", _utc_date(2), "")]
    assert (reopened["completed"], reopened["version"]) == (False, 2)

    await _abackdate(async_sqlite_db)
    await async_sqlite_db.calculate_metrics()
    rebuilt = (await _astored_aggregate_metrics_rows(async_sqlite_db))[("daily", _utc_date(2), "")]
    assert rebuilt["completed"] is True
    assert _aggregate_metrics_numbers(rebuilt) == (1, 3, 167)

    await async_sqlite_db.upsert_sessions([_session("new_session", "carol", [], _noon_utc(2))])
    assert (await _astored_aggregate_metrics_rows(async_sqlite_db))[("daily", _utc_date(2), "")]["completed"] is False


@pytest.mark.asyncio
async def test_async_calculate_metrics_skips_a_rebuild_already_running(async_sqlite_db):
    """Ensure a calculation returns None at once while another worker holds the refresh, a stale lock reads as failed
    and is taken over, and a stopped calculation releases the refresh"""
    refreshes_table = await async_sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert (await async_sqlite_db._claim_metrics_refresh(refreshes_table, "other-worker"))["status"] == "running"
    assert await async_sqlite_db.calculate_metrics() is None
    assert (await async_sqlite_db.get_metrics_refresh_status())["status"] == "running"
    assert await _astored_rows(async_sqlite_db) == {}

    async with async_sqlite_db.async_session_factory() as sess, sess.begin():
        await sess.execute(
            update(refreshes_table)
            .where(refreshes_table.c.id == METRICS_REFRESH_ID)
            .values(locked_at=int(time.time()) - METRICS_LOCK_SECONDS)
        )
    status = await async_sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert await async_sqlite_db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = await async_sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"], status["finished_at"]) == ("failed", METRICS_STOPPED_ERROR, None)
    assert await async_sqlite_db.calculate_metrics()
    status = await async_sqlite_db.get_metrics_refresh_status()
    assert status["status"] == "completed" and status["finished_at"] is not None

    async_sqlite_db.stop_metrics_refresh_on_read()
    assert async_sqlite_db._metrics_refreshed_at == float("inf")


@pytest.mark.asyncio
async def test_async_calculate_metrics_dates_releases_the_lock_when_cancelled(async_sqlite_db, monkeypatch):
    """Ensure a calculation cancelled mid-build, as on shutdown, releases the metrics refresh instead of holding it"""

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(async_sqlite_db, "_calculate_date_metrics", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await async_sqlite_db.calculate_metrics_dates()

    refresh_status = await async_sqlite_db.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)
