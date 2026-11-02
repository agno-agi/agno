"""Unit tests for the component metrics related methods of the SqliteDb and AsyncSqliteDb classes"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session as OrmSession

from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.db.sqlite.utils import build_component_metrics_runs_query, reopen_metrics_day
from agno.db.utils import METRICS_LOCK_SECONDS, METRICS_REFRESH_ID, METRICS_STOPPED_ERROR
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession


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


def _ground_truth_sessions() -> list:
    """An agent, a team with a member and a workflow; two users and no user; three days; cache tokens; and a run
    paused on an old day, which a later save completes."""
    sessions: list = []
    for days_ago in [5, 2, 0]:
        created_at = _noon_utc(days_ago)
        for user_id in ["alice", "bob", None]:
            owner = user_id or "nobody"
            sessions.append(
                _session(
                    f"agent_{owner}_{days_ago}",
                    user_id,
                    [
                        _run(f"agent_run_{owner}_{days_ago}", user_id, 10, 5, created_at, cache_read_tokens=3),
                        _run(f"agent_run_2_{owner}_{days_ago}", user_id, 1, 1, created_at + 60),
                    ],
                    created_at,
                )
            )
        team_run_id = f"team_run_{days_ago}"
        sessions.append(
            TeamSession(
                session_id=f"team_{days_ago}",
                team_id="team-1",
                user_id="alice",
                runs=[
                    TeamRunOutput(
                        run_id=team_run_id,
                        team_id="team-1",
                        user_id="alice",
                        status=RunStatus.completed,
                        model="gpt-5",
                        model_provider="OpenAI",
                        metrics=RunMetrics(input_tokens=30, output_tokens=20, total_tokens=50, cache_read_tokens=7),
                        created_at=created_at + 120,
                    ),
                    _run(
                        f"member_run_{days_ago}",
                        "alice",
                        40,
                        10,
                        created_at + 120,
                        agent_id="agent-2",
                        parent_run_id=team_run_id,
                    ),
                ],
                created_at=created_at + 120,
                updated_at=created_at + 120,
            )
        )
        sessions.append(
            WorkflowSession(
                session_id=f"workflow_{days_ago}",
                workflow_id="workflow-1",
                user_id="bob",
                runs=[
                    WorkflowRunOutput(
                        run_id=f"workflow_run_{days_ago}",
                        workflow_id="workflow-1",
                        user_id="bob",
                        status=RunStatus.completed,
                        created_at=created_at + 180,
                    )
                ],
                created_at=created_at + 180,
                updated_at=created_at + 180,
            )
        )
    # Paused on the oldest day; a later save completes it
    sessions.append(
        _session(
            "paused_session",
            "bob",
            [_run("paused_run", "bob", 8, 2, _noon_utc(5) + 240, status=RunStatus.paused)],
            _noon_utc(5) + 240,
        )
    )
    return sessions


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


def _stored_totals_rows(db: SqliteDb) -> Dict[tuple, Dict]:
    """Every day and month row of agno_user_metrics, keyed by (aggregation_period, date, user_id)."""
    table = db._get_table("user_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.aggregation_period, row.date, row.user_id): dict(row._mapping)
            for row in sess.execute(select(table)).fetchall()
        }


async def _astored_totals_rows(db: AsyncSqliteDb) -> Dict[tuple, Dict]:
    """Every day and month row of agno_user_metrics, keyed by (aggregation_period, date, user_id)."""
    table = await db._get_table("user_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        return {
            (row.aggregation_period, row.date, row.user_id): dict(row._mapping)
            for row in (await sess.execute(select(table))).fetchall()
        }


def _day_versions(db: SqliteDb, starting_date: date, ending_date: date) -> Dict[date, int]:
    """The version of each day's everyone row of agno_user_metrics in the date range."""
    return {
        key[1]: row["version"]
        for key, row in _stored_totals_rows(db).items()
        if key[0] == "daily" and key[2] == "" and starting_date <= key[1] <= ending_date
    }


def _numbers(row: Dict) -> tuple:
    """The sessions, runs and total tokens of a component metrics row."""
    return row["sessions_count"], row["runs_count"], row["total_tokens"]


def _totals_numbers(row: Dict) -> tuple:
    """The sessions, runs and total tokens of a user metrics row."""
    return (
        row["agent_sessions_count"] + row["team_sessions_count"] + row["workflow_sessions_count"],
        row["agent_runs_count"] + row["team_runs_count"] + row["workflow_runs_count"],
        row["total_tokens"],
    )


_GROUND_TRUTH_SESSIONS_SQL = """
SELECT date(created_at, 'unixepoch') AS day, COALESCE(user_id, '') AS user_id, session_type, COUNT(*) AS count
FROM agno_sessions GROUP BY 1, 2, 3
"""

_GROUND_TRUTH_RUNS_SQL = """
SELECT date(created_at, 'unixepoch') AS day, COALESCE(user_id, '') AS user_id, run_type,
    COUNT(*) AS runs, SUM(parent_run_id IS NULL) AS root_runs,
    SUM(COALESCE(json_extract(run_data, '$.metrics.input_tokens'), 0)) AS input_tokens,
    SUM(COALESCE(json_extract(run_data, '$.metrics.total_tokens'), 0)) AS total_tokens,
    SUM(COALESCE(json_extract(run_data, '$.metrics.cache_read_tokens'), 0)) AS cache_read_tokens,
    SUM(status = 'COMPLETED') AS completed
FROM agno_runs GROUP BY 1, 2, 3
"""


def _ground_truth(rows: List, day: date, user_id: Optional[str]) -> Dict[str, int]:
    """Add up the ground truth rows of a day, for every user or one: ``""`` for the runs with no user."""
    totals: Dict[str, int] = {}
    for row in rows:
        if row.day != day.isoformat() or (user_id is not None and row.user_id != user_id):
            continue
        for key, value in row._mapping.items():
            if key in ["day", "user_id", "session_type", "run_type"]:
                continue
            name = f"{getattr(row, 'session_type', None) or row.run_type}_{key}"
            totals[name] = totals.get(name, 0) + int(value)
            totals[key] = totals.get(key, 0) + int(value)
    return totals


def _check_ground_truth(sessions_rows: List, runs_rows: List, user_metrics_rows: Dict[tuple, Dict], day: date) -> None:
    """Check the everyone row and every user row of a day against a direct count of its sessions and runs."""
    for user_id in ["", "alice", "bob"]:
        expected = {
            **_ground_truth(sessions_rows, day, user_id or None),
            **_ground_truth(runs_rows, day, user_id or None),
        }
        row = user_metrics_rows[("daily", day, user_id)]
        for component_type in ["agent", "team", "workflow"]:
            assert row[f"{component_type}_sessions_count"] == expected.get(f"{component_type}_count", 0)
            assert row[f"{component_type}_runs_count"] == expected.get(f"{component_type}_runs", 0)
        assert row["root_runs_count"] == expected["root_runs"]
        assert row["input_tokens"] == expected["input_tokens"]
        assert row["total_tokens"] == expected["total_tokens"]
        assert row["token_details"].get("cache_read_tokens", 0) == expected["cache_read_tokens"]
        assert row["status_metrics"].get("COMPLETED", 0) == expected["completed"]
        assert row["users_count"] == (2 if user_id == "" else 1)


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


def test_calculate_month_metrics_in_batches(sqlite_db, monkeypatch):
    """Ensure a month read a row at a time adds up the rows of all its days"""
    monkeypatch.setattr("agno.db.sqlite.sqlite.METRICS_BATCH_SIZE", 1)
    # Another day of the same month as bob's old session
    days_ago = 71 if _utc_date(70).day > 1 else 69
    _persist(
        sqlite_db,
        _session(
            "bob_older_session", "bob", [_run("bob_older_run", "bob", 2, 1, _noon_utc(days_ago))], _noon_utc(days_ago)
        ),
    )
    _backdate(sqlite_db)
    sqlite_db.calculate_metrics()

    month_start = _utc_date(70).replace(day=1)
    assert _totals_numbers(_stored_totals_rows(sqlite_db)[("monthly", month_start, "")]) == (2, 2, 33)


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


def _model_metrics(input_tokens: int, output_tokens: int, duration: Optional[float] = None) -> RunMetrics:
    """The metrics of a run whose model answered: tokens, its duration in seconds, and the model that served it."""
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        duration=duration,
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
    )


def _assistant_message(duration: float) -> Message:
    """An assistant message that recorded how long its model request took, in seconds."""
    return Message(role="assistant", content="Hello", metrics=MessageMetrics(duration=duration))


def test_calculate_metrics_skips_messages_carried_over_from_history(tmp_path):
    """Ensure a message carried over from an earlier run is not counted as a model call of this one"""
    db = SqliteDb(db_file=str(tmp_path / "history.db"))
    run = _run("history_run", "alice", 10, 5, _noon_utc(2))
    run.messages = [
        Message(role="assistant", content="Earlier", from_history=True, metrics=MessageMetrics(duration=9.9)),
        _assistant_message(1.2),
    ]
    _persist(db, _session("history_session", "alice", [run], _noon_utc(2)))
    _backdate(db)

    db.calculate_metrics()

    row = _stored_rows(db)[(_utc_date(2), "alice", "agent", "agent-1")]
    assert row["model_calls_count"] == 1
    assert row["total_model_call_ms"] == 1200
    assert row["model_call_buckets"] == {"le_1200": 1}


def test_calculate_metrics_skips_messages_a_forked_run_copied(tmp_path):
    """Ensure the messages a forked run copied from the run it was forked from are not counted again"""
    db = SqliteDb(db_file=str(tmp_path / "fork.db"))
    original = _run("original_run", "alice", 10, 5, _noon_utc(2))
    original.messages = [_assistant_message(1.5)]
    forked = _run("forked_run", "alice", 20, 5, _noon_utc(2))
    forked.messages = [_assistant_message(1.5), _assistant_message(0.5)]
    forked.forked_from_run_id = original.run_id
    forked.forked_from_message_index = 1
    _persist(db, _session("fork_session", "alice", [original, forked], _noon_utc(2)))
    _backdate(db)

    db.calculate_metrics()

    row = _stored_rows(db)[(_utc_date(2), "alice", "agent", "agent-1")]
    assert (row["runs_count"], row["total_tokens"]) == (2, 40)
    assert (row["model_calls_count"], row["total_model_call_ms"]) == (2, 2000)


def test_calculate_metrics_counts_nested_runs_at_every_depth(tmp_path):
    """Ensure the runs nested inside a run are counted at every depth, from only what is read of them, and a run with
    none nested walks none"""
    db = SqliteDb(db_file=str(tmp_path / "nested.db"))
    inner_member = _run("nested_inner_member", None, 2, 1, _noon_utc(2))
    inner_member.messages = [_assistant_message(0.4)]
    inner_team = TeamRunOutput(
        run_id="nested_inner_team",
        team_id="inner-team",
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_model_metrics(3, 1),
        messages=[_assistant_message(0.5)],
        member_responses=[inner_member],
    )
    member = _run("nested_member", None, 4, 2, _noon_utc(2), agent_id="agent-2")
    member.messages = [
        Message(role="assistant", content="Earlier", from_history=True, metrics=MessageMetrics(duration=9.9)),
        _assistant_message(0.6),
    ]
    team_run = TeamRunOutput(
        run_id="nested_team_run",
        team_id="team-1",
        user_id="alice",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_model_metrics(10, 5, duration=2.0),
        messages=[_assistant_message(1.2)],
        member_responses=[member, inner_team],
        created_at=_noon_utc(2),
    )
    _persist(
        db,
        TeamSession(
            session_id="nested_session", team_id="team-1", user_id="alice", runs=[team_run], created_at=_noon_utc(2)
        ),
    )
    _persist(db, _session("flat_session", "alice", [_run("flat_run", "alice", 1, 1, _noon_utc(2) + 1)], _noon_utc(2)))
    _backdate(db)

    runs_table = db._get_table("runs")
    with db.Session() as sess:
        rows = {
            row.run_id: row
            for row in sess.execute(build_component_metrics_runs_query(runs_table, _noon_utc(2), _noon_utc(2) + 2))
        }
    assert rows["flat_run"].nested_runs is None
    nested_runs = sorted(json.loads(rows["nested_team_run"].nested_runs), key=lambda nested_run: nested_run["path"])
    assert [(nested_run["depth"], nested_run["run_id"]) for nested_run in nested_runs] == [
        (1, "nested_member"),
        (1, "nested_inner_team"),
        (2, "nested_inner_member"),
    ]
    assert all("messages" not in nested_run for nested_run in nested_runs)
    assert [nested_run["call_durations"] for nested_run in nested_runs] == [[0.6], [0.5], [0.4]]

    db.calculate_metrics()

    # The nested runs are no runs of their own, so their tokens and calls are on the row of the team run
    row = _stored_rows(db)[(_utc_date(2), "alice", "team", "team-1")]
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (19, 9, 28)
    assert row["model_calls_count"] == 4
    assert row["total_model_call_ms"] == 2700
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 4}}}


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


def test_get_metrics_totals(sqlite_db):
    """Ensure the totals of a date range are one record, a completed month read from its month row"""
    sqlite_db.calculate_metrics()
    totals, latest_updated_at = sqlite_db.get_metrics_totals(_utc_date(80), _utc_date(0))

    assert (totals["sessions_count"], totals["root_runs_count"], totals["total_tokens"]) == (3, 4, 495)
    assert totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4, "cost": None}]
    assert latest_updated_at is not None


def test_get_metrics_versions(sqlite_db):
    """Ensure the versions are None until a first calculation has finished, then key every everyone row of the date
    range by period and date, and move for a reopened day once it is rebuilt"""
    sqlite_db.stop_metrics_refresh_on_read()
    assert sqlite_db.get_metrics_versions(_utc_date(80), _utc_date(0)) is None

    sqlite_db.calculate_metrics()
    month_start = _utc_date(70).replace(day=1)
    versions = sqlite_db.get_metrics_versions(month_start, _utc_date(0))
    assert versions[f"daily {_utc_date(2).isoformat()}"] == 1
    assert f"monthly {month_start.isoformat()}" in versions
    assert set(versions) >= {f"daily {_utc_date(day).isoformat()}" for day in [70, 2, 1, 0]}
    # Only the rows dated inside the date range, a month row by its first day
    only_day = _utc_date(2) if _utc_date(2).day != 1 else _utc_date(70)
    assert sqlite_db.get_metrics_versions(only_day, only_day) == {f"daily {only_day.isoformat()}": 1}

    sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    _backdate(sqlite_db)
    sqlite_db.calculate_metrics()
    rebuilt = sqlite_db.get_metrics_versions(month_start, _utc_date(0))
    # Reopened once and rebuilt once, with its month; no other row moves
    moved = {key for key in versions if rebuilt[key] != versions[key]}
    assert moved == {f"daily {_utc_date(2).isoformat()}", f"monthly {_utc_date(2).replace(day=1).isoformat()}"}
    assert rebuilt[f"daily {_utc_date(2).isoformat()}"] == 3


def test_calculate_metrics_with_nothing_new_leaves_every_version(sqlite_db):
    """Ensure a calculation with no new session or run rebuilds no day, and returns today's metrics"""
    _persist(
        sqlite_db, _session("today_session", "alice", [_run("today_run", "alice", 1, 1, _noon_utc(0))], _noon_utc(0))
    )
    _backdate(sqlite_db)
    assert sqlite_db.calculate_metrics()
    versions = _day_versions(sqlite_db, _utc_date(80), _utc_date(0))

    metrics = sqlite_db.calculate_metrics()
    assert [(metric["date"], metric["user_id"], metric["agent_runs_count"]) for metric in metrics] == [
        (_utc_date(0), "alice", 1)
    ]
    assert _day_versions(sqlite_db, _utc_date(80), _utc_date(0)) == versions


def test_get_metrics_omits_days_without_sessions_or_runs(sqlite_db):
    """Ensure a day the calculation keeps an everyone row of zeros for is not returned"""
    sqlite_db.calculate_metrics()
    assert ("daily", _utc_date(1), "") in _stored_totals_rows(sqlite_db)
    assert sqlite_db.get_metrics_by_date(_utc_date(1), _utc_date(0)) == ([], None)
    by_date, _ = sqlite_db.get_metrics_by_date(_utc_date(3), _utc_date(0))
    assert [metric["date"] for metric in by_date] == [_utc_date(2)]


def _save_today_run(db: SqliteDb, run_id: str) -> None:
    """Save one more run of bob's today, updated before the current second."""
    db.upsert_run(_run(run_id, "bob", 1, 2, _noon_utc(0)), session_id="bob_session", user_id="bob")
    _backdate(db)


def _today_runs(db: SqliteDb) -> List[int]:
    """The runs get_metrics returns for today, the read refreshing first when it may."""
    metrics, _ = db.get_metrics(_utc_date(0), _utc_date(0))
    return [metric["agent_runs_count"] for metric in metrics]


def test_metrics_calculation_disabled_stops_the_refresh_on_read(sqlite_db, monkeypatch):
    """Ensure METRICS_CALCULATION_ENABLED=false stops the refresh a read would run"""
    sqlite_db.calculate_metrics()
    _save_today_run(sqlite_db, "today_run_1")
    monkeypatch.setenv("METRICS_CALCULATION_ENABLED", "false")
    sqlite_db._metrics_refreshed_at = 0.0
    assert _today_runs(sqlite_db) == []

    monkeypatch.setenv("METRICS_CALCULATION_ENABLED", "true")
    sqlite_db._metrics_refreshed_at = 0.0
    assert _today_runs(sqlite_db) == [1]


def test_stop_metrics_refresh_on_read(sqlite_db):
    """Ensure a database whose metrics are calculated in the background never calculates them on a read"""
    sqlite_db.calculate_metrics()
    _save_today_run(sqlite_db, "today_run_1")
    sqlite_db.stop_metrics_refresh_on_read()
    assert sqlite_db._metrics_refreshed_at == float("inf")
    assert _today_runs(sqlite_db) == []


def test_calculate_metrics_matches_a_direct_count(tmp_path):
    """Ensure the totals rows of every day, user and month match a direct count of the sessions and runs, and a
    paused run completed later is counted as completed once its day is rebuilt"""
    db = SqliteDb(db_file=str(tmp_path / "ground_truth.db"))
    for session in _ground_truth_sessions():
        _persist(db, session)
    _backdate(db)
    db.calculate_metrics()
    assert db.get_metrics_refresh_status()["status"] == "completed"
    totals = _stored_totals_rows(db)
    assert totals[("daily", _utc_date(5), "bob")]["status_metrics"]["PAUSED"] == 1
    # Only the days with data, yesterday and today; yesterday's everyone row is zeros
    assert sorted(key[1] for key in totals if key[0] == "daily" and key[2] == "") == [
        _utc_date(days_ago) for days_ago in [5, 2, 1, 0]
    ]
    assert _totals_numbers(totals[("daily", _utc_date(1), "")]) == (0, 0, 0)
    assert (totals[("daily", _utc_date(5), "")]["completed"], totals[("daily", _utc_date(5), "")]["version"]) == (
        True,
        1,
    )
    assert totals[("daily", _utc_date(0), "")]["completed"] is False
    # A month's totals rows add up its days
    month_start = _utc_date(0).replace(day=1)
    month_days = [row for key, row in totals.items() if key[0] == "daily" and key[2] == "" and key[1] >= month_start]
    assert _totals_numbers(totals[("monthly", month_start, "")]) == tuple(
        map(sum, zip(*[_totals_numbers(row) for row in month_days]))
    )
    rows = _stored_rows(db)
    # The component metrics table keeps day rows only
    assert {row["aggregation_period"] for row in rows.values()} == {"daily"}
    assert _numbers(rows[(_utc_date(2), "alice", "agent", "agent-1")]) == (1, 2, 17)
    assert rows[(_utc_date(2), "alice", "agent", "agent-1")]["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}

    # The paused run is completed: its stored created_at keeps it on its day, which the save reopens
    paused_run = _run("paused_run", "bob", 8, 2, _noon_utc(0))
    db.upsert_run(paused_run, session_id="paused_session", user_id="bob")
    assert _stored_totals_rows(db)[("daily", _utc_date(5), "")]["completed"] is False
    _backdate(db)
    db.calculate_metrics()

    with db.Session() as sess:
        sessions_rows = sess.execute(text(_GROUND_TRUTH_SESSIONS_SQL)).fetchall()
        runs_rows = sess.execute(text(_GROUND_TRUTH_RUNS_SQL)).fetchall()
    totals = _stored_totals_rows(db)
    for days_ago in [5, 2, 0]:
        _check_ground_truth(sessions_rows, runs_rows, totals, _utc_date(days_ago))
    assert "PAUSED" not in totals[("daily", _utc_date(5), "bob")]["status_metrics"]
    assert totals[("daily", _utc_date(5), "")]["completed"] is True
    # The member run was started by the team run, so it is no root run, and is kept under its parent
    member_row = _stored_rows(db)[(_utc_date(2), "alice", "agent", "agent-2")]
    assert (member_row["parent_component_id"], member_row["root_component_id"]) == ("team-1", "team-1")
    # The runs with no user are read from their component rows
    unowned, _ = db.get_component_metrics(_utc_date(2), _utc_date(2), user_id="", fields=["total_tokens"])
    assert unowned == [{"date": _utc_date(2), "total_tokens": 17}]


def test_calculate_metrics_rebuilds_a_reopened_day(sqlite_db):
    """Ensure a run saved on a completed day reopens the day, and the next calculation counts it"""
    sqlite_db.calculate_metrics()
    version = _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["version"]

    sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    reopened = _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]
    assert (reopened["completed"], reopened["version"]) == (False, version + 1)

    _backdate(sqlite_db)
    sqlite_db.calculate_metrics()
    rebuilt = _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]
    assert rebuilt["completed"] is True
    assert _totals_numbers(rebuilt) == (2, 4, 467)


def test_session_save_reopens_the_day_the_session_is_stored_on(sqlite_db):
    """Ensure a session save reopens its day when the session is new or changes owner, and not otherwise"""
    sqlite_db.calculate_metrics()
    alice_session = _sample_sessions()[0]
    sqlite_db.upsert_session(alice_session)
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is True

    sqlite_db.upsert_sessions([_session("new_session", "carol", [], _noon_utc(2))])
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is False


def test_deleting_a_session_keeps_its_closed_day_closed(sqlite_db):
    """Ensure a delete never reopens the day it removes a session from"""
    sqlite_db.calculate_metrics()
    sqlite_db.delete_session("bob_session")
    sqlite_db.delete_run("alice_run_2")
    stored = _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]
    assert (stored["completed"], stored["version"]) == (True, 1)
    _backdate(sqlite_db)
    assert sqlite_db.calculate_metrics() == []


def test_cancelling_a_pending_run_reopens_its_day(sqlite_db):
    """Ensure a pending run cancelled on a closed day reopens it"""
    _persist(
        sqlite_db,
        _session(
            "pending_session",
            "alice",
            [_run("pending_run", "alice", 0, 0, _noon_utc(2), status=RunStatus.pending)],
            _noon_utc(2),
        ),
    )
    _backdate(sqlite_db)
    sqlite_db.calculate_metrics()
    assert sqlite_db.cancel_pending_run("pending_run", session_id="pending_session", reason="stop", user_id="alice")
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is False


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(sqlite_db):
    """Ensure rebuild_from rebuilds every day with data from that date, one with no totals row included, and none
    before it"""
    sqlite_db.calculate_metrics()
    user_metrics_table = sqlite_db._get_table("user_metrics")
    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(user_metrics_table.delete().where(user_metrics_table.c.date == _utc_date(2)))

    calculated = sqlite_db.calculate_metrics(rebuild_from=_utc_date(3))
    assert sorted({metric["date"] for metric in calculated}) == [_utc_date(2)]
    totals = _stored_totals_rows(sqlite_db)
    assert _totals_numbers(totals[("daily", _utc_date(2), "")]) == (2, 3, 465)
    assert totals[("daily", _utc_date(2), "")]["completed"] is True
    assert totals[("daily", _utc_date(70), "")]["version"] == 1


def test_a_legacy_run_is_counted_on_its_own_day(tmp_path):
    """Ensure a run kept only in the legacy runs column is counted on its own day, which holds no session or run of
    the tables"""
    db_file = str(tmp_path / "legacy_day.db")
    db = SqliteDb(db_file=db_file)
    session = _session("legacy_session", "carol", [_run("legacy_run", "carol", 20, 0, _noon_utc(4))], _noon_utc(6))
    db.upsert_session(session)
    with db.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN runs JSON"))
        sess.execute(
            text("UPDATE agno_sessions SET runs = :runs, updated_at = :updated_at"),
            {"runs": json.dumps([run.to_dict() for run in session.runs]), "updated_at": _noon_utc(3)},
        )
    db.upsert_schema_version(db.session_table_name, "2.5.0")

    legacy_db = SqliteDb(db_file=db_file)
    legacy_db.calculate_metrics()
    totals = _stored_totals_rows(legacy_db)
    assert _totals_numbers(totals[("daily", _utc_date(4), "")]) == (0, 1, 20)
    assert _totals_numbers(totals[("daily", _utc_date(6), "")]) == (1, 0, 0)


def _set_refresh_row(db: SqliteDb, **values) -> None:
    """Change the row of the metrics refreshes table, as another process would."""
    refreshes_table = db._get_table("metrics_refreshes", create_table_if_not_found=True)
    with db.Session() as sess, sess.begin():
        sess.execute(update(refreshes_table).where(refreshes_table.c.id == METRICS_REFRESH_ID).values(**values))


def test_calculate_metrics_skips_a_rebuild_already_running(sqlite_db):
    """Ensure a calculation returns None at once while another worker holds the refresh"""
    refreshes_table = sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert sqlite_db._claim_metrics_refresh(refreshes_table, "other-worker")["status"] == "running"
    assert sqlite_db.calculate_metrics() is None
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["finished_at"]) == ("running", None)
    assert _stored_rows(sqlite_db) == {}


def test_calculate_metrics_takes_over_a_lock_that_went_stale(sqlite_db):
    """Ensure a lock whose heartbeat went stale reads as failed and is taken over by the next calculation"""
    refreshes_table = sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)
    sqlite_db._claim_metrics_refresh(refreshes_table, "other-worker")
    _set_refresh_row(sqlite_db, locked_at=int(time.time()) - METRICS_LOCK_SECONDS)
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert sqlite_db.calculate_metrics()
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)
    assert status["finished_at"] is not None


def test_calculate_metrics_records_a_failed_refresh(sqlite_db, monkeypatch):
    """Ensure a calculation that fails is released as failed with its error, and finished_at stays the time of the
    last completed one"""
    sqlite_db.calculate_metrics()
    finished_at = sqlite_db.get_metrics_refresh_status()["finished_at"]
    sqlite_db.upsert_run(_run("today_run", "alice", 1, 1, _noon_utc(0)), session_id="alice_session", user_id="alice")
    _backdate(sqlite_db)

    def _fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("agno.db.sqlite.sqlite.calculate_date_component_metrics", _fail)
    with pytest.raises(RuntimeError):
        sqlite_db.calculate_metrics()
    status = sqlite_db.get_metrics_refresh_status()
    assert (status["status"], status["error"], status["finished_at"]) == ("failed", "boom", None)
    refreshes_table = sqlite_db._get_table("metrics_refreshes")
    refresh_row, _ = sqlite_db._get_metrics_refresh_row(refreshes_table)
    assert (refresh_row["locked_by"], refresh_row["finished_at"]) == (None, finished_at)


def test_a_day_is_never_written_by_a_process_that_lost_the_lock(sqlite_db, monkeypatch):
    """Ensure a calculation whose refresh another process took over writes nothing more"""
    refreshes_table = sqlite_db._get_table("metrics_refreshes", create_table_if_not_found=True)

    def _take_over(self, sess, table, worker_id):
        sess.execute(update(table).where(table.c.id == METRICS_REFRESH_ID).values(locked_by="other-worker"))
        return False

    monkeypatch.setattr(SqliteDb, "_heartbeat_metrics_refresh", _take_over)
    assert sqlite_db.calculate_metrics() is None
    assert _stored_rows(sqlite_db) == {}
    assert sqlite_db._claim_metrics_refresh(refreshes_table, "third-worker") is None


def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(sqlite_db, monkeypatch):
    """Ensure a day reopened between the read of its version and the write of its rows stays open for the next
    calculation"""
    sqlite_db.calculate_metrics()
    sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    _backdate(sqlite_db)
    user_metrics_table = sqlite_db._get_table("user_metrics")
    heartbeat_metrics_refresh = SqliteDb._heartbeat_metrics_refresh

    def _reopen_before_the_write(self, sess, refreshes_table, worker_id):
        # Another session, as a write committed after the day was read and before its rows are written
        with OrmSession(self.db_engine) as other, other.begin():
            reopen_metrics_day(session=other, table=user_metrics_table, day=_utc_date(2))
        return heartbeat_metrics_refresh(self, sess, refreshes_table, worker_id)

    with monkeypatch.context() as patch:
        patch.setattr(SqliteDb, "_heartbeat_metrics_refresh", _reopen_before_the_write)
        sqlite_db.calculate_metrics()
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is False

    sqlite_db.calculate_metrics()
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is True


def test_a_run_save_never_fails_because_of_metrics(sqlite_db):
    """Ensure a save whose reopen fails is stored, and the day is reopened by the next write"""
    sqlite_db.calculate_metrics()
    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(
            text(
                "CREATE TRIGGER refuse_totals_writes BEFORE UPDATE ON agno_user_metrics "
                "BEGIN SELECT RAISE(ABORT, 'refused'); END"
            )
        )
    sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    assert sqlite_db.get_run("alice_run_3") is not None
    assert sqlite_db._metrics_days_not_reopened == {_utc_date(2)}
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is True

    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(text("DROP TRIGGER refuse_totals_writes"))
    sqlite_db.upsert_run(_run("today_run", "alice", 1, 1, _noon_utc(0)), session_id="alice_session", user_id="alice")
    assert sqlite_db._metrics_days_not_reopened == set()
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is False


def test_upsert_session_without_a_user_metrics_table(sqlite_db):
    """Ensure a session and its run of a past day are saved before any user metrics table exists"""
    _persist(
        sqlite_db, _session("alice_9_days_ago", "alice", [_run("old_run", "alice", 1, 1, _noon_utc(9))], _noon_utc(9))
    )
    assert sqlite_db.get_session("alice_9_days_ago") is not None
    assert sqlite_db.get_run("old_run") is not None
    assert sqlite_db.table_exists(sqlite_db.user_metrics_table_name) is False


def test_a_save_of_a_closed_day_from_a_fresh_process_is_stored(sqlite_db):
    """Ensure a process that never read the user metrics table reopens a day on its first save"""
    sqlite_db.calculate_metrics()
    fresh_db = SqliteDb(db_file=sqlite_db.db_file)
    fresh_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    assert _stored_totals_rows(sqlite_db)[("daily", _utc_date(2), "")]["completed"] is False


def test_a_stopped_calculation_releases_the_lock(sqlite_db):
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


def test_a_calculation_stops_between_the_batches_of_a_day(sqlite_db, monkeypatch):
    """Ensure a stop is seen between the batches of a day's runs, and the day is left unwritten"""
    monkeypatch.setattr("agno.db.sqlite.sqlite.METRICS_BATCH_SIZE", 1)
    checks: List[int] = []

    def _should_stop() -> bool:
        # Before the old day and its one batch, then before the day of three runs and its first batch; the second
        # batch of that day stops it
        checks.append(1)
        return len(checks) > 4

    assert sqlite_db.calculate_metrics_dates(should_stop=_should_stop) is None
    assert {key[0] for key in _stored_rows(sqlite_db)} == {_utc_date(70)}
    assert sqlite_db.get_metrics_refresh_status()["error"] == METRICS_STOPPED_ERROR


def test_a_month_a_stopped_calculation_left_open_is_rebuilt_by_the_next(sqlite_db, monkeypatch):
    """Ensure a day rebuilt by a calculation that stops before its months reopens the month, the month is read from
    its days while open, and the next calculation rebuilds it"""
    sqlite_db.calculate_metrics()
    month_start = _utc_date(70).replace(day=1)
    sqlite_db.upsert_run(_run("bob_old_run_2", "bob", 5, 5, _noon_utc(70) + 60), session_id="bob_old_session")
    _backdate(sqlite_db)

    stop: List[bool] = []
    calculate_date_metrics = SqliteDb._calculate_date_metrics

    def _stop_after_the_day(self, *args, **kwargs):
        written = calculate_date_metrics(self, *args, **kwargs)
        stop.append(True)
        return written

    with monkeypatch.context() as patch:
        patch.setattr(SqliteDb, "_calculate_date_metrics", _stop_after_the_day)
        assert sqlite_db.calculate_metrics_dates(should_stop=lambda: bool(stop)) is None
    month_row = _stored_totals_rows(sqlite_db)[("monthly", month_start, "")]
    assert (month_row["completed"], month_row["total_tokens"]) == (False, 30)
    totals, _ = sqlite_db.get_metrics_totals(month_start, _utc_date(70), fields=["total_tokens"])
    assert totals["total_tokens"] == 40

    sqlite_db.calculate_metrics()
    month_row = _stored_totals_rows(sqlite_db)[("monthly", month_start, "")]
    assert (month_row["completed"], month_row["total_tokens"]) == (True, 40)


def test_a_nested_run_also_kept_as_a_legacy_run_is_counted_once(tmp_path):
    """Ensure a member run kept both inside its team's legacy run and as a legacy run of its own, on the next day, is
    counted once, on its own row"""
    db_file = str(tmp_path / "legacy_member.db")
    db = SqliteDb(db_file=db_file)
    member = _run("legacy_member_run", "carol", 40, 10, _noon_utc(1), agent_id="agent-2", parent_run_id="team_run")
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        user_id="carol",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_model_metrics(30, 20),
        member_responses=[member],
        created_at=_noon_utc(2),
    )
    session = TeamSession(session_id="legacy_team_session", team_id="team-1", user_id="carol", created_at=_noon_utc(2))
    db.upsert_session(session)
    with db.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN runs JSON"))
        sess.execute(
            text("UPDATE agno_sessions SET runs = :runs"), {"runs": json.dumps([team_run.to_dict(), member.to_dict()])}
        )
    db.upsert_schema_version(db.session_table_name, "2.5.0")

    legacy_db = SqliteDb(db_file=db_file)
    legacy_db.calculate_metrics()
    rows = _stored_rows(legacy_db)
    assert rows[(_utc_date(2), "carol", "team", "team-1")]["total_tokens"] == 50
    assert rows[(_utc_date(1), "carol", "agent", "agent-2")]["total_tokens"] == 50


def test_get_metrics_reads_the_metrics_table_until_the_first_calculation_finished(sqlite_db):
    """Ensure a read never runs a first calculation while the deprecated metrics table has rows, and reads it until
    the first calculation has finished"""
    metrics_table = sqlite_db._get_table("metrics", create_table_if_not_found=True)
    with sqlite_db.Session() as sess, sess.begin():
        sess.execute(
            metrics_table.insert().values(
                {
                    "id": "stored_metrics_row",
                    "date": _utc_date(2),
                    "aggregation_period": "daily",
                    "user_id": "alice",
                    "agent_sessions_count": 7,
                    "token_metrics": {},
                    "model_metrics": [],
                    "created_at": int(time.time()),
                    "completed": True,
                }
            )
        )

    metrics, _ = sqlite_db.get_metrics()
    assert [(row["id"], row["agent_sessions_count"]) for row in metrics] == [("stored_metrics_row", 7)]
    assert sqlite_db.get_metrics_refresh_status() is None

    sqlite_db.calculate_metrics()
    metrics, _ = sqlite_db.get_metrics(user_id="alice")
    assert [(row["date"], row["user_id"], row["agent_sessions_count"]) for row in metrics] == [
        (_utc_date(2), "alice", 1)
    ]


def test_get_metrics_runs_a_first_calculation_without_deprecated_rows(sqlite_db):
    """Ensure a read runs the first calculation when the deprecated metrics table has no rows, and refreshes after"""
    metrics, _ = sqlite_db.get_metrics(user_id="alice")
    assert [(row["date"], row["agent_runs_count"]) for row in metrics] == [(_utc_date(2), 2)]
    assert sqlite_db.get_metrics_refresh_status()["status"] == "completed"

    _persist(
        sqlite_db,
        _session("alice_today_session", "alice", [_run("alice_run_3", "alice", 1, 1, _noon_utc(0))], _noon_utc(0)),
    )
    # The last refresh on read was a minute ago
    sqlite_db._metrics_refreshed_at = 0.0
    metrics, _ = sqlite_db.get_metrics(user_id="alice")
    assert [(row["date"], row["agent_runs_count"]) for row in metrics] == [(_utc_date(2), 2), (_utc_date(0), 1)]


# =============================================================================
# Async AsyncSqliteDb
# =============================================================================


@pytest.mark.asyncio
async def test_async_calculate_metrics(async_sqlite_db):
    """Ensure a calculation stores one row per owner, component and day, a totals row per day and user, and the
    totals rows of a month"""
    await async_sqlite_db.calculate_metrics()

    rows = await _astored_rows(async_sqlite_db)
    assert _numbers(rows[(_utc_date(2), "alice", "agent", "agent-1")]) == (1, 2, 165)
    assert _numbers(rows[(_utc_date(2), "bob", "agent", "agent-1")]) == (1, 1, 300)
    assert rows[(_utc_date(2), "alice", "agent", "agent-1")]["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}

    totals = await _astored_totals_rows(async_sqlite_db)
    assert _totals_numbers(totals[("daily", _utc_date(2), "")]) == (2, 3, 465)
    assert _totals_numbers(totals[("daily", _utc_date(2), "alice")]) == (1, 2, 165)
    assert totals[("daily", _utc_date(2), "")]["completed"] is True
    assert totals[("daily", _utc_date(0), "")]["completed"] is False
    assert sorted(key[1] for key in totals if key[0] == "daily" and key[2] == "") == [
        _utc_date(70),
        _utc_date(2),
        _utc_date(1),
        _utc_date(0),
    ]

    month_start = _utc_date(70).replace(day=1)
    assert _totals_numbers(totals[("monthly", month_start, "")]) == (1, 1, 30)
    assert (await async_sqlite_db.get_metrics_refresh_status())["status"] == "completed"


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
async def test_async_get_metrics_versions(async_sqlite_db):
    """Ensure the versions are None until a first calculation has finished, then key every everyone row of the date
    range by period and date, and move for a reopened day once it is rebuilt"""
    async_sqlite_db.stop_metrics_refresh_on_read()
    assert await async_sqlite_db.get_metrics_versions(_utc_date(80), _utc_date(0)) is None

    await async_sqlite_db.calculate_metrics()
    month_start = _utc_date(70).replace(day=1)
    versions = await async_sqlite_db.get_metrics_versions(month_start, _utc_date(0))
    assert versions[f"daily {_utc_date(2).isoformat()}"] == 1
    assert f"monthly {month_start.isoformat()}" in versions

    await async_sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    await _abackdate(async_sqlite_db)
    await async_sqlite_db.calculate_metrics()
    rebuilt = await async_sqlite_db.get_metrics_versions(month_start, _utc_date(0))
    moved = {key for key in versions if rebuilt[key] != versions[key]}
    assert moved == {f"daily {_utc_date(2).isoformat()}", f"monthly {_utc_date(2).replace(day=1).isoformat()}"}


@pytest.mark.asyncio
async def test_async_saves_reopen_a_closed_day_and_deletes_do_not(async_sqlite_db):
    """Ensure a run save, a cancel and a session that moves reopen a closed day, and a delete or an unchanged session
    save does not"""
    await async_sqlite_db.calculate_metrics()
    await async_sqlite_db.delete_session("bob_session")
    await async_sqlite_db.upsert_session(_sample_sessions()[0])
    assert (await _astored_totals_rows(async_sqlite_db))[("daily", _utc_date(2), "")]["completed"] is True

    await async_sqlite_db.upsert_run(
        _run("alice_run_3", "alice", 1, 1, _noon_utc(2) + 120), session_id="alice_session", user_id="alice"
    )
    reopened = (await _astored_totals_rows(async_sqlite_db))[("daily", _utc_date(2), "")]
    assert (reopened["completed"], reopened["version"]) == (False, 2)

    await _abackdate(async_sqlite_db)
    await async_sqlite_db.calculate_metrics()
    rebuilt = (await _astored_totals_rows(async_sqlite_db))[("daily", _utc_date(2), "")]
    assert rebuilt["completed"] is True
    assert _totals_numbers(rebuilt) == (1, 3, 167)

    await async_sqlite_db.upsert_sessions([_session("new_session", "carol", [], _noon_utc(2))])
    assert (await _astored_totals_rows(async_sqlite_db))[("daily", _utc_date(2), "")]["completed"] is False


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
async def test_async_a_cancelled_calculation_releases_the_lock(async_sqlite_db, monkeypatch):
    """Ensure a calculation cancelled mid-build, as on shutdown, releases the metrics refresh instead of holding it"""

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(async_sqlite_db, "_calculate_date_metrics", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await async_sqlite_db.calculate_metrics_dates()

    refresh_status = await async_sqlite_db.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)
