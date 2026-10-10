"""Integration tests for the OS Metrics related methods of the PostgresDb class"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest
from sqlalchemy import inspect, select, text

from agno.db.postgres.postgres import PostgresDb
from agno.db.postgres.utils import build_os_metrics_runs_query
from agno.db.utils import (
    calculate_date_os_metrics,
    merge_os_metrics_totals,
    resolve_os_metrics_fields,
    total_os_metrics_records,
)
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest.fixture(autouse=True)
def cleanup_os_metrics_sessions_and_runs(postgres_db_real: PostgresDb):
    """Fixture to clean-up OS metrics, session and run rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            os_metrics_table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
            session.execute(os_metrics_table.delete())
            runs_table = postgres_db_real._get_table("runs", create_table_if_not_found=True)
            session.execute(runs_table.delete())
            sessions_table = postgres_db_real._get_table("sessions", create_table_if_not_found=True)
            session.execute(sessions_table.delete())
            session.commit()
        except Exception:
            session.rollback()


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back.

    The sessions below are laid an hour apart from this point, so every one of them lands in
    the UTC day ``days_ago`` days back whatever the current time of day is.
    """
    day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int):
    """The UTC day ``days_ago`` days back, the day an OS metrics row is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _persist(db: PostgresDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table.

    ``upsert_session`` stopped writing the runs column when runs were normalised out, so an
    OS metrics test that only called it would count no runs at all.
    """
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _run_metrics(input_tokens: int, output_tokens: int, duration=None, time_to_first_token=None) -> RunMetrics:
    """The metrics a finished run carries: tokens, timings in seconds, and the model that served it."""
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        duration=duration,
        time_to_first_token=time_to_first_token,
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


def _stored_rows(db: PostgresDb) -> Dict[tuple, Dict]:
    """Every OS metrics row in the table, keyed by (date, user_id, agent_id, team_id, workflow_id)

    The total rows and month rows are left out: see ``_stored_total_rows``.
    """
    table = db._get_table("os_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.date, row.user_id, row.agent_id, row.team_id, row.workflow_id): dict(row._mapping)
            for row in sess.execute(select(table).where(table.c.aggregation_period == "daily")).fetchall()
        }


def _stored_total_rows(db: PostgresDb) -> Dict[tuple, Dict]:
    """Every total row and month row in the table, keyed by its date, period, owner and component"""
    table = db._get_table("os_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (
                row.date,
                row.aggregation_period,
                row.user_id,
                row.agent_id,
                row.team_id,
                row.workflow_id,
            ): dict(row._mapping)
            for row in sess.execute(
                select(table).where(table.c.aggregation_period.in_(["daily_total", "monthly", "monthly_total"]))
            ).fetchall()
        }


@pytest.fixture
def sample_sessions_for_os_metrics() -> List:
    """Fixture returning the sessions of one past day, plus one of today.

    Two days ago: alice has an agent session with a completed run and an error run, bob has an
    agent session and a team session whose team run has a member run, and one agent session
    has no owner. Today: alice has one more agent session.
    """
    base_time = _noon_utc(2)

    alice_agent_session = AgentSession(
        session_id="alice_agent_session",
        agent_id="agent-1",
        user_id="alice",
        session_data={"session_name": "Alice Agent Session"},
        agent_data={"name": "Agent 1", "model": "gpt-5"},
        runs=[
            RunOutput(
                run_id="alice_run_completed",
                agent_id="agent-1",
                user_id="alice",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(100, 50, duration=2.0, time_to_first_token=0.5),
                messages=[_assistant_message(1.5)],
                created_at=base_time,
            ),
            RunOutput(
                run_id="alice_run_error",
                agent_id="agent-1",
                user_id="alice",
                status=RunStatus.error,
                model="gpt-5",
                model_provider="OpenAI",
                # A model that failed before answering reports tokens but no details
                metrics=RunMetrics(input_tokens=10, output_tokens=0, total_tokens=10),
                messages=[],
                created_at=base_time + 60,
            ),
        ],
        created_at=base_time,
        updated_at=base_time,
    )

    bob_agent_session = AgentSession(
        session_id="bob_agent_session",
        agent_id="agent-1",
        user_id="bob",
        session_data={"session_name": "Bob Agent Session"},
        agent_data={"name": "Agent 1", "model": "gpt-5"},
        runs=[
            RunOutput(
                run_id="bob_run_completed",
                agent_id="agent-1",
                user_id="bob",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(200, 100, duration=4.0, time_to_first_token=1.0),
                messages=[_assistant_message(2.5)],
                created_at=base_time + 3600,
            )
        ],
        created_at=base_time + 3600,
        updated_at=base_time + 3600,
    )

    bob_team_session = TeamSession(
        session_id="bob_team_session",
        team_id="team-1",
        user_id="bob",
        session_data={"session_name": "Bob Team Session"},
        team_data={"name": "Team 1", "model": "gpt-5"},
        runs=[
            TeamRunOutput(
                run_id="bob_team_run",
                team_id="team-1",
                user_id="bob",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(30, 20, duration=3.0),
                messages=[],
                created_at=base_time + 7200,
            ),
            RunOutput(
                run_id="bob_member_run",
                agent_id="agent-2",
                user_id="bob",
                parent_run_id="bob_team_run",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(40, 10, duration=1.0),
                messages=[],
                created_at=base_time + 7200,
            ),
        ],
        created_at=base_time + 7200,
        updated_at=base_time + 7200,
    )

    unowned_agent_session = AgentSession(
        session_id="unowned_agent_session",
        agent_id="agent-1",
        user_id=None,
        session_data={"session_name": "Unowned Agent Session"},
        agent_data={"name": "Agent 1", "model": "gpt-5"},
        runs=[
            RunOutput(
                run_id="unowned_run_completed",
                agent_id="agent-1",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(5, 5),
                messages=[],
                created_at=base_time + 10800,
            )
        ],
        created_at=base_time + 10800,
        updated_at=base_time + 10800,
    )

    today_time = _noon_utc(0)
    alice_today_session = AgentSession(
        session_id="alice_today_session",
        agent_id="agent-1",
        user_id="alice",
        session_data={"session_name": "Alice Today Session"},
        agent_data={"name": "Agent 1", "model": "gpt-5"},
        runs=[
            RunOutput(
                run_id="alice_today_run",
                agent_id="agent-1",
                user_id="alice",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(1, 1),
                messages=[],
                created_at=today_time,
            )
        ],
        created_at=today_time,
        updated_at=today_time,
    )

    return [alice_agent_session, bob_agent_session, bob_team_session, unowned_agent_session, alice_today_session]


# The run statuses as the rows key them
COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value

# The rows the past day's sessions produce, one per owner and component
PAST_DAY_ROW_KEYS = [
    ("alice", "agent-1", "", ""),
    ("bob", "agent-1", "", ""),
    ("bob", "", "team-1", ""),
    ("bob", "agent-2", "", ""),
    ("", "agent-1", "", ""),
]


def test_os_metrics_table_creation(postgres_db_real: PostgresDb):
    """Ensure the OS metrics table is created with its columns, unique constraint and indexes"""
    os_metrics_table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)

    assert os_metrics_table is not None
    assert os_metrics_table.name == postgres_db_real.os_metrics_table_name
    assert os_metrics_table.schema == postgres_db_real.db_schema

    column_names = [col.name for col in os_metrics_table.columns]
    expected_columns = [
        "id",
        "date",
        "aggregation_period",
        "user_id",
        "agent_id",
        "team_id",
        "workflow_id",
        "parent_id",
        "sessions_count",
        "runs_count",
        "status_metrics",
        "token_metrics",
        "duration_metrics",
        "model_metrics",
        "metadata",
        "created_at",
        "updated_at",
        "completed",
    ]
    for col in expected_columns:
        assert col in column_names, f"Missing column: {col}"

    inspector = inspect(postgres_db_real.db_engine)
    unique_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in inspector.get_unique_constraints(os_metrics_table.name, schema=os_metrics_table.schema)
    }
    assert unique_constraints[f"{os_metrics_table.name}_uq_os_metrics_user_date_period_component"] == [
        "user_id",
        "date",
        "aggregation_period",
        "agent_id",
        "team_id",
        "workflow_id",
        "parent_id",
    ]

    indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes(os_metrics_table.name, schema=os_metrics_table.schema)
    }
    assert indexes[f"idx_{os_metrics_table.name}_date"] == ["date"]


def test_calculate_os_metrics_no_sessions(postgres_db_real: PostgresDb):
    """Ensure the calculate_os_metrics method returns None when there are no sessions"""
    result = postgres_db_real.calculate_os_metrics()

    assert result is None


def test_calculate_os_metrics_skips_a_rebuild_already_running(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure the lazy rebuild behind a read writes nothing while another process holds the rebuild lock"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)

    # Another process is rebuilding: its transaction holds the lock until it commits
    with postgres_db_real.db_engine.connect() as other, other.begin():
        other.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('agno_os_metrics'), hashtext(:table_name))"),
            {"table_name": table.fullname},
        )

        assert postgres_db_real._calculate_os_metrics(wait_for_rebuild=False) is None
        assert _stored_rows(postgres_db_real) == {}
        # A skipped rebuild does not count as a refresh, so the next read tries again
        assert postgres_db_real._os_metrics_refreshed_at == 0.0

    # Nobody holds the lock any more, so the same call rebuilds
    result = postgres_db_real._calculate_os_metrics(wait_for_rebuild=False)
    assert result is not None
    assert len(_stored_rows(postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


def test_calculate_os_metrics_skips_messages_carried_over_from_history(postgres_db_real):
    """Ensure a message carried over from an earlier run is not counted as a model call of this one"""
    session = AgentSession(
        session_id="history_session",
        agent_id="agent-1",
        user_id="alice",
        runs=[
            RunOutput(
                run_id="history_run",
                agent_id="agent-1",
                user_id="alice",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(10, 5, duration=2.0),
                messages=[
                    Message(
                        role="assistant", content="Earlier", from_history=True, metrics=MessageMetrics(duration=9.9)
                    ),
                    _assistant_message(1.2),
                ],
                created_at=_noon_utc(2),
            )
        ],
        created_at=_noon_utc(2),
    )
    _persist(postgres_db_real, session)

    postgres_db_real.calculate_os_metrics()

    row = _stored_rows(postgres_db_real)[(_utc_date(2), "alice", "agent-1", "", "")]
    assert row["duration_metrics"]["model_calls_count"] == 1
    assert row["duration_metrics"]["total_model_call_ms"] == 1200
    assert row["duration_metrics"]["model_call_ms_buckets"] == {"le_1200": 1}


def test_calculate_os_metrics(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure calculate_os_metrics writes one row per owner and component for each day"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)

    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    # The past day's rows with its total row, and today's row
    assert len(result) == len(PAST_DAY_ROW_KEYS) + 2

    past_day = _utc_date(2)
    today = _utc_date(0)
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == len(PAST_DAY_ROW_KEYS) + 1

    # Rows are unique by day, owner and component, so every row can be found by that key
    for key in PAST_DAY_ROW_KEYS:
        assert (past_day, *key) in stored_rows
    today_row = stored_rows[(today, "alice", "agent-1", "", "")]

    # A past day's rows are complete, today's are not
    assert all(row["completed"] is True for row in stored_rows.values() if row["date"] == past_day)
    assert today_row["completed"] is False
    assert today_row["sessions_count"] == 1
    assert today_row["runs_count"] == 1

    alice_row = stored_rows[(past_day, "alice", "agent-1", "", "")]
    assert alice_row["date"] == past_day
    assert alice_row["aggregation_period"] == "daily"
    assert alice_row["user_id"] == "alice"
    assert alice_row["agent_id"] == "agent-1"
    assert alice_row["team_id"] == ""
    assert alice_row["workflow_id"] == ""
    assert alice_row["sessions_count"] == 1
    assert alice_row["runs_count"] == 2
    assert alice_row["status_metrics"] == {COMPLETED: 1, ERROR: 1}
    # The error run's zero output tokens add nothing, and no zero key is stored
    assert alice_row["token_metrics"] == {"input_tokens": 110, "output_tokens": 50, "total_tokens": 160}
    assert alice_row["duration_metrics"] == {
        "duration_runs_count": 1,
        "total_duration_ms": 2000,
        "max_duration_ms": 2000,
        "duration_ms_buckets": {"le_2000": 1},
        "time_to_first_token_runs_count": 1,
        "total_time_to_first_token_ms": 500,
        "max_time_to_first_token_ms": 500,
        "time_to_first_token_ms_buckets": {"le_500": 1},
        "model_calls_count": 1,
        "total_model_call_ms": 1500,
        "max_model_call_ms": 1500,
        "model_call_ms_buckets": {"le_1500": 1},
    }
    # The error run reported no details, so only the completed run's model is counted
    assert alice_row["model_metrics"] == [
        {
            "model_id": "gpt-5",
            "model_provider": "OpenAI",
            "agent_id": "agent-1",
            "count": 1,
        }
    ]
    assert alice_row["metadata"] is None
    assert alice_row["created_at"] is not None
    assert alice_row["updated_at"] is not None

    # The team run counts under the team, its member's run under the member agent
    team_row = stored_rows[(past_day, "bob", "", "team-1", "")]
    assert team_row["sessions_count"] == 1
    assert team_row["runs_count"] == 1
    assert team_row["model_metrics"][0]["team_id"] == "team-1"
    member_row = stored_rows[(past_day, "bob", "agent-2", "", "")]
    assert team_row["parent_id"] == ""
    assert member_row["sessions_count"] == 0
    assert member_row["runs_count"] == 1
    assert member_row["token_metrics"] == {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
    assert member_row["parent_id"] == "team-1"

    unowned_row = stored_rows[(past_day, "", "agent-1", "", "")]
    assert unowned_row["user_id"] == ""
    assert unowned_row["sessions_count"] == 1
    assert unowned_row["runs_count"] == 1


def test_calculate_os_metrics_rewrites_only_changed_rows(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild leaves unchanged rows alone, rewrites a changed row and drops a stale one"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)

    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    row_count = len(_stored_rows(postgres_db_real))

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().values(updated_at=1))

    # Nothing changed: the past day is complete so only yesterday and today are rebuilt, and no row is written
    today = _utc_date(0)
    alice_today_row_id = (today, "alice", "agent-1", "", "")
    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    assert [(row["date"], row["user_id"], row["agent_id"], row["team_id"], row["workflow_id"]) for row in result] == [
        alice_today_row_id
    ]
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert all(row["updated_at"] == 1 for row in stored_rows.values())

    # One more run for alice's session today: only that row is rewritten
    alice_today_session = sample_sessions_for_os_metrics[4]
    postgres_db_real.upsert_run(
        RunOutput(
            run_id="alice_today_run_2",
            agent_id="agent-1",
            user_id="alice",
            status=RunStatus.completed,
            model="gpt-5",
            model_provider="OpenAI",
            metrics=_run_metrics(7, 3),
            messages=[],
            created_at=alice_today_session.created_at + 60,
        ),
        session_id=alice_today_session.session_id,
        user_id=alice_today_session.user_id,
        run_index=1,
    )
    postgres_db_real.calculate_os_metrics()
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert stored_rows[alice_today_row_id]["runs_count"] == 2
    assert stored_rows[alice_today_row_id]["updated_at"] != 1
    assert all(row["updated_at"] == 1 for row_id, row in stored_rows.items() if row_id != alice_today_row_id)

    # A session of bob's today adds his row; once the session and its run go, the row is deleted
    bob_today_session = AgentSession(
        session_id="bob_today_session",
        agent_id="agent-1",
        user_id="bob",
        runs=[
            RunOutput(
                run_id="bob_today_run",
                agent_id="agent-1",
                user_id="bob",
                status=RunStatus.completed,
                messages=[],
                created_at=alice_today_session.created_at,
            )
        ],
        created_at=alice_today_session.created_at,
        updated_at=alice_today_session.created_at,
    )
    _persist(postgres_db_real, bob_today_session)
    postgres_db_real.calculate_os_metrics()
    bob_today_row_id = (today, "bob", "agent-1", "", "")
    assert bob_today_row_id in _stored_rows(postgres_db_real)

    assert postgres_db_real.delete_session("bob_today_session") is True
    postgres_db_real.calculate_os_metrics()
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert bob_today_row_id not in stored_rows


def test_get_os_metrics_by_date(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals the rows of each day, for every owner or one"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    today = _utc_date(0)

    # Every owner: one dict per day, oldest first, with every field
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today)
    assert latest_updated_at is not None
    assert [m["date"] for m in metrics] == [past_day, today]
    past_day_totals = metrics[0]
    assert set(past_day_totals) == {
        "date",
        "sessions_count",
        "runs_count",
        "status_metrics",
        "token_metrics",
        "duration_metrics",
        "model_metrics",
        "duration_buckets",
    }
    assert past_day_totals["sessions_count"] == 4
    assert past_day_totals["runs_count"] == 6
    assert past_day_totals["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert past_day_totals["token_metrics"] == {"input_tokens": 385, "output_tokens": 185, "total_tokens": 570}
    assert past_day_totals["duration_metrics"] == {
        "duration_runs_count": 4,
        "total_duration_ms": 10000,
        "max_duration_ms": 4000,
        "time_to_first_token_runs_count": 2,
        "total_time_to_first_token_ms": 1500,
        "max_time_to_first_token_ms": 1000,
        "model_calls_count": 2,
        "total_model_call_ms": 4000,
        "max_model_call_ms": 2500,
    }
    # One entry per model and caller, in no set order
    model_metrics = sorted(
        past_day_totals["model_metrics"], key=lambda m: (m.get("agent_id", ""), m.get("team_id", ""))
    )
    assert model_metrics == [
        {
            "model_id": "gpt-5",
            "model_provider": "OpenAI",
            "team_id": "team-1",
            "count": 1,
        },
        {
            "model_id": "gpt-5",
            "model_provider": "OpenAI",
            "agent_id": "agent-1",
            "count": 3,
        },
        {
            "model_id": "gpt-5",
            "model_provider": "OpenAI",
            "agent_id": "agent-2",
            "count": 1,
        },
    ]
    assert metrics[1]["sessions_count"] == 1
    assert metrics[1]["runs_count"] == 1

    # The latest updated_at of the window is the one returned
    stored_rows = _stored_rows(postgres_db_real)
    assert latest_updated_at == max(row["updated_at"] for row in stored_rows.values())

    # One owner: only bob's rows are summed
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, user_id="bob")
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 2
    assert metrics[0]["runs_count"] == 3
    assert metrics[0]["token_metrics"] == {"input_tokens": 270, "output_tokens": 130, "total_tokens": 400}

    # The empty owner: only the unowned rows
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, user_id="")
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 1
    assert metrics[0]["runs_count"] == 1
    assert metrics[0]["token_metrics"] == {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}


def test_get_os_metrics_fields(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics returns only the fields asked for, with the buckets only on request"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=past_day, fields=["duration_metrics"]
    )
    assert set(metrics[0]) == {"date", "duration_metrics"}
    assert not any(key.endswith("_buckets") for key in metrics[0]["duration_metrics"])

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=past_day, fields=["duration_metrics", "duration_buckets"]
    )
    assert set(metrics[0]) == {"date", "duration_metrics", "duration_buckets"}
    assert not any(key.endswith("_buckets") for key in metrics[0]["duration_metrics"])
    assert metrics[0]["duration_buckets"] == {
        "duration_ms_buckets": {"le_1000": 1, "le_2000": 1, "le_3000": 1, "le_4000": 1},
        "time_to_first_token_ms_buckets": {"le_500": 1, "le_1000": 1},
        "model_call_ms_buckets": {"le_1500": 1, "le_2500": 1},
    }

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=past_day, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [{"date": past_day, "sessions_count": 4, "runs_count": 6}]

    with pytest.raises(ValueError):
        postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=past_day, fields=["users_count"])


def test_get_os_metrics_refreshes_rows(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics builds the rows itself when they have not been refreshed yet"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    assert _stored_rows(postgres_db_real) == {}

    past_day = _utc_date(2)
    today = _utc_date(0)
    postgres_db_real._os_metrics_refreshed_at = 0
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    )

    assert latest_updated_at is not None
    assert metrics == [{"date": past_day, "sessions_count": 4}, {"date": today, "sessions_count": 1}]
    assert len(_stored_rows(postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


def test_get_os_metrics_no_rows(postgres_db_real: PostgresDb):
    """Ensure get_os_metrics returns nothing when there are no sessions"""
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(starting_date=_utc_date(2), ending_date=_utc_date(0))

    assert metrics == []
    assert latest_updated_at is None


@pytest.fixture
def sample_multi_day_sessions_for_os_metrics() -> List[AgentSession]:
    """Fixture returning one owner's agent sessions on two different days"""
    sessions = []
    for days_ago, session_count in ((3, 2), (2, 1)):
        base_time = _noon_utc(days_ago)
        for i in range(session_count):
            sessions.append(
                AgentSession(
                    session_id=f"day_{days_ago}_session_{i}",
                    agent_id="agent-1",
                    user_id="alice",
                    session_data={"session_name": f"Day {days_ago} Session {i}"},
                    agent_data={"name": "Agent 1", "model": "gpt-5"},
                    runs=[
                        RunOutput(
                            run_id=f"day_{days_ago}_run_{i}",
                            agent_id="agent-1",
                            user_id="alice",
                            status=RunStatus.completed,
                            messages=[],
                            created_at=base_time + (i * 3600),
                        )
                    ],
                    created_at=base_time + (i * 3600),
                    updated_at=base_time + (i * 3600),
                )
            )
    return sessions


def test_os_metrics_multiple_days(postgres_db_real: PostgresDb, sample_multi_day_sessions_for_os_metrics):
    """Ensure sessions on two days produce rows on both, and a one-day window returns only that day"""
    for session in sample_multi_day_sessions_for_os_metrics:
        _persist(postgres_db_real, session)

    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    # Each day's row, with the day's total row
    assert len(result) == 4

    first_day = _utc_date(3)
    second_day = _utc_date(2)
    stored_rows = _stored_rows(postgres_db_real)
    assert {row["date"] for row in stored_rows.values()} == {first_day, second_day}

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=first_day, ending_date=second_day, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [
        {"date": first_day, "sessions_count": 2, "runs_count": 2},
        {"date": second_day, "sessions_count": 1, "runs_count": 1},
    ]

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=second_day, ending_date=second_day, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [{"date": second_day, "sessions_count": 1, "runs_count": 1}]


def _month_start(months_ago: int):
    """The first day of the calendar month ``months_ago`` months back."""
    month_start = datetime.now(timezone.utc).date().replace(day=1)
    for _ in range(months_ago):
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    return month_start


def _session_on(day, session_id: str, user_id, input_tokens: int = 10) -> AgentSession:
    """An agent session created at midday UTC of the given day, with one completed run."""
    created_at = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
    return AgentSession(
        session_id=session_id,
        agent_id="agent-1",
        user_id=user_id,
        runs=[
            RunOutput(
                run_id=f"{session_id}_run",
                agent_id="agent-1",
                user_id=user_id,
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(input_tokens, 5, duration=2.0),
                messages=[_assistant_message(1.5)],
                created_at=created_at,
            )
        ],
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.fixture
def sample_multi_month_sessions_for_os_metrics() -> List[AgentSession]:
    """Fixture returning sessions in two completed months, plus one of today.

    Three months back: alice and an unowned session on the 1st, alice and bob on the 15th.
    Two months back: bob on the 10th. Today: alice.
    """
    first_month = _month_start(3)
    second_month = _month_start(2)
    return [
        _session_on(first_month, "first_month_alice_1", "alice", input_tokens=100),
        _session_on(first_month, "first_month_unowned", None, input_tokens=5),
        _session_on(first_month + timedelta(days=14), "first_month_alice_2", "alice", input_tokens=20),
        _session_on(first_month + timedelta(days=14), "first_month_bob", "bob", input_tokens=40),
        _session_on(second_month + timedelta(days=9), "second_month_bob", "bob", input_tokens=70),
        _session_on(_utc_date(0), "today_alice", "alice", input_tokens=1),
    ]


def _comparable(totals):
    """Totals with their model entries in a set order, as the database returns them in none."""
    totals = [totals] if isinstance(totals, dict) else totals
    return [
        {
            **entry,
            "model_metrics": sorted(
                entry.get("model_metrics", []), key=lambda m: (m.get("agent_id", ""), m.get("team_id", ""))
            ),
        }
        for entry in totals
    ]


def _stored_month_rows(db: PostgresDb) -> Dict[tuple, Dict]:
    """Every month row in the table, keyed as in ``_stored_total_rows``"""
    return {key: row for key, row in _stored_total_rows(db).items() if key[1] in ("monthly", "monthly_total")}


def _sessions_counts(db: PostgresDb, day, user_id) -> List[int]:
    """The sessions_count of each day get_os_metrics returns for the given day, for every owner or one"""
    metrics, _ = db.get_os_metrics(starting_date=day, ending_date=day, user_id=user_id, fields=["sessions_count"])
    return [day_totals["sessions_count"] for day_totals in metrics]


def _total_sessions_count(db: PostgresDb, starting_date, ending_date, user_id=None) -> int:
    """The sessions_count get_os_metrics_totals returns for the date range, for every owner or one"""
    totals, _ = db.get_os_metrics_totals(
        starting_date=starting_date, ending_date=ending_date, user_id=user_id, fields=["sessions_count"]
    )
    return totals["sessions_count"]


def test_calculate_os_metrics_writes_a_total_row_for_a_completed_day(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a completed day gets one total row for every owner, and an open day none"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    stored_rows = _stored_rows(postgres_db_real)
    total_rows = _stored_total_rows(postgres_db_real)
    assert set(total_rows) == {(past_day, "daily_total", "", "", "", "")}

    day_row = total_rows[(past_day, "daily_total", "", "", "", "")]
    assert day_row["sessions_count"] == 4
    assert day_row["runs_count"] == 6
    assert day_row["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert day_row["token_metrics"] == {"input_tokens": 385, "output_tokens": 185, "total_tokens": 570}
    # The bucket objects are kept inside duration_metrics, as in a row
    assert day_row["duration_metrics"]["duration_runs_count"] == 4
    assert day_row["duration_metrics"]["max_duration_ms"] == 4000
    assert day_row["duration_metrics"]["duration_ms_buckets"] == {
        "le_1000": 1,
        "le_2000": 1,
        "le_3000": 1,
        "le_4000": 1,
    }
    assert sum(model["count"] for model in day_row["model_metrics"]) == 5
    assert day_row["completed"] is True
    # A total row reports when the rows it totals were written
    assert day_row["updated_at"] == max(row["updated_at"] for row in stored_rows.values() if row["date"] == past_day)


def test_get_os_metrics_reads_a_completed_day_from_its_total_row(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a read equals the sum of the rows, with a completed day read from its total row for every owner"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    today = _utc_date(0)
    stored_rows = list(_stored_rows(postgres_db_real).values())
    fields = resolve_os_metrics_fields(None)

    # Every owner, then one owner: the same totals as the rows add up to
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today)
    expected, expected_updated_at = total_os_metrics_records(stored_rows, fields)
    assert _comparable(metrics) == _comparable(expected)
    assert latest_updated_at == expected_updated_at
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=today, user_id="bob"
    )
    expected, expected_updated_at = total_os_metrics_records(
        [row for row in stored_rows if row["user_id"] == "bob"], fields
    )
    assert _comparable(metrics) == _comparable(expected)
    assert latest_updated_at == expected_updated_at

    # Change every row: for every owner the past day is still read from its total row and today from its rows
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.aggregation_period == "daily").values(sessions_count=50))
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, fields=["sessions_count"])
    assert metrics == [{"date": past_day, "sessions_count": 4}, {"date": today, "sessions_count": 50}]
    # One owner is read from that owner's rows on every day: bob has three rows on the past day
    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=today, user_id="bob", fields=["sessions_count"]
    )
    assert metrics == [{"date": past_day, "sessions_count": 150}]


def test_get_os_metrics_reads_a_day_without_a_total_row_from_its_rows(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a day whose total row is missing is read from its rows"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    today = _utc_date(0)
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.delete().where(table.c.aggregation_period == "daily_total"))

    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, fields=["sessions_count"])
    assert metrics == [{"date": past_day, "sessions_count": 4}, {"date": today, "sessions_count": 1}]


def test_get_os_metrics_never_reads_a_total_row_for_one_owner(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure one owner's read uses only that owner's rows, and the empty owner's never the row of every owner"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.aggregation_period == "daily_total").values(sessions_count=1000))

    assert _sessions_counts(postgres_db_real, past_day, None) == [1000]
    assert _sessions_counts(postgres_db_real, past_day, "alice") == [1]
    assert _sessions_counts(postgres_db_real, past_day, "bob") == [2]
    # The unowned row, not the total row of every owner, which also has an empty user_id
    assert _sessions_counts(postgres_db_real, past_day, "") == [1]
    assert _sessions_counts(postgres_db_real, past_day, "carol") == []


def test_calculate_os_metrics_writes_month_rows_for_a_completed_month(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a completed month gets a total row and a row per owner and component, and this month none"""
    for session in sample_multi_month_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    stored_rows = _stored_rows(postgres_db_real)
    month_rows = _stored_month_rows(postgres_db_real)
    assert set(month_rows) == {
        (first_month, "monthly_total", "", "", "", ""),
        (first_month, "monthly", "", "agent-1", "", ""),
        (first_month, "monthly", "alice", "agent-1", "", ""),
        (first_month, "monthly", "bob", "agent-1", "", ""),
        (second_month, "monthly_total", "", "", "", ""),
        (second_month, "monthly", "bob", "agent-1", "", ""),
    }

    month_row = month_rows[(first_month, "monthly_total", "", "", "", "")]
    assert month_row["sessions_count"] == 4
    assert month_row["runs_count"] == 4
    assert month_row["token_metrics"] == {"input_tokens": 165, "output_tokens": 20, "total_tokens": 185}
    assert month_row["duration_metrics"]["duration_ms_buckets"] == {"le_2000": 4}
    assert month_row["completed"] is True
    alice_row = month_rows[(first_month, "monthly", "alice", "agent-1", "", "")]
    assert alice_row["sessions_count"] == 2
    assert alice_row["token_metrics"]["input_tokens"] == 120
    assert alice_row["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "agent_id": "agent-1", "count": 2}
    ]
    assert month_rows[(first_month, "monthly", "", "agent-1", "", "")]["sessions_count"] == 1
    assert month_rows[(second_month, "monthly_total", "", "", "", "")]["sessions_count"] == 1
    # A month row reports when the rows it totals were written
    assert month_row["updated_at"] == max(
        row["updated_at"] for row in stored_rows.values() if row["date"] < second_month
    )

    # The month rows are no rows of the first day of their month: a rebuild leaves them alone
    postgres_db_real.calculate_os_metrics()
    assert _stored_month_rows(postgres_db_real) == month_rows


def test_calculate_os_metrics_calculates_a_month_once_none_of_its_days_is_open(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a month with an open day gets no month rows, and a later rebuild writes them once it has none"""
    for session in sample_multi_month_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)

    # The first month loses its month rows and has a day still open
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            table.delete().where(
                table.c.date == first_month, table.c.aggregation_period.in_(["monthly", "monthly_total"])
            )
        )
        sess.execute(
            table.update()
            .where(table.c.date == first_month, table.c.aggregation_period == "daily", table.c.user_id == "alice")
            .values(completed=False)
        )
    postgres_db_real.calculate_os_metrics()
    assert set(_stored_month_rows(postgres_db_real)) == {
        (second_month, "monthly_total", "", "", "", ""),
        (second_month, "monthly", "bob", "agent-1", "", ""),
    }

    # None of its days is rebuilt again, and the next rebuild still calculates it
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().where(table.c.date == first_month).values(completed=True))
    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    assert {row["date"] for row in result} == {_utc_date(0)}
    assert set(_stored_month_rows(postgres_db_real)) == {
        (first_month, "monthly_total", "", "", "", ""),
        (first_month, "monthly", "", "agent-1", "", ""),
        (first_month, "monthly", "alice", "agent-1", "", ""),
        (first_month, "monthly", "bob", "agent-1", "", ""),
        (second_month, "monthly_total", "", "", "", ""),
        (second_month, "monthly", "bob", "agent-1", "", ""),
    }


def test_get_os_metrics_totals(postgres_db_real: PostgresDb, sample_multi_month_sessions_for_os_metrics):
    """Ensure the totals of a date range equal its days' totals summed, for every owner or one"""
    for session in sample_multi_month_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    today = _utc_date(0)
    fields = resolve_os_metrics_fields(None)
    windows = [
        # A whole month, part of a month, and both months with every day since
        (first_month, second_month - timedelta(days=1)),
        (first_month + timedelta(days=9), second_month + timedelta(days=9)),
        (first_month, today),
    ]
    for starting_date, ending_date in windows:
        for user_id in (None, "alice", "bob", "", "carol"):
            totals, latest_updated_at = postgres_db_real.get_os_metrics_totals(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            metrics, expected_updated_at = postgres_db_real.get_os_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            assert _comparable(totals) == _comparable(merge_os_metrics_totals(metrics, fields))
            assert latest_updated_at == expected_updated_at

    totals, _ = postgres_db_real.get_os_metrics_totals(
        starting_date=first_month, ending_date=today, fields=["sessions_count", "runs_count"]
    )
    assert totals == {"sessions_count": 6, "runs_count": 6}
    totals, latest_updated_at = postgres_db_real.get_os_metrics_totals(
        starting_date=first_month, ending_date=today, user_id="carol", fields=["sessions_count", "model_metrics"]
    )
    assert totals == {"sessions_count": 0, "model_metrics": []}
    assert latest_updated_at is None


def test_get_os_metrics_totals_reads_a_whole_month_from_its_month_rows(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a month inside the date range is read from its month rows, each owner from their own"""
    for session in sample_multi_month_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            table.update()
            .where(table.c.date == first_month, table.c.aggregation_period == "monthly_total")
            .values(sessions_count=1000)
        )
        sess.execute(
            table.update()
            .where(table.c.date == first_month, table.c.aggregation_period == "monthly", table.c.user_id == "bob")
            .values(sessions_count=500)
        )

    # The whole first month comes from its month row, with the days after it added
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1)) == 1000
    assert _total_sessions_count(postgres_db_real, first_month, _utc_date(0)) == 1002
    # A month partly outside the date range is read from its days
    assert (
        _total_sessions_count(postgres_db_real, first_month + timedelta(days=1), second_month - timedelta(days=1)) == 2
    )
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=2)) == 4
    # One owner's month comes from that owner's month rows, and the empty owner's never from the row of every owner
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1), "alice") == 2
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1), "bob") == 500
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1), "") == 1
    # The read of each day never uses a month row
    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), fields=["sessions_count"]
    )
    assert metrics == [
        {"date": first_month, "sessions_count": 2},
        {"date": first_month + timedelta(days=14), "sessions_count": 2},
    ]


def test_refresh_os_metrics_reports_what_changed(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure refresh_os_metrics reports a change only when the rebuild wrote or deleted a row"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)

    previous_updated_at, updated_at, changed = postgres_db_real.refresh_os_metrics()
    assert previous_updated_at is None
    assert updated_at is not None
    assert changed is True

    # Nothing new: no row is written, and the table was last updated when it was before
    assert postgres_db_real.refresh_os_metrics() == (updated_at, updated_at, False)

    # One more run today: reported even when it lands in the same second as the rebuild before it
    alice_today_session = sample_sessions_for_os_metrics[4]
    postgres_db_real.upsert_run(
        RunOutput(
            run_id="alice_today_run_2",
            agent_id="agent-1",
            user_id="alice",
            status=RunStatus.completed,
            messages=[],
            created_at=alice_today_session.created_at + 60,
        ),
        session_id=alice_today_session.session_id,
        user_id=alice_today_session.user_id,
        run_index=1,
    )
    previous_updated_at, latest_updated_at, changed = postgres_db_real.refresh_os_metrics()
    assert previous_updated_at == updated_at
    assert latest_updated_at >= updated_at
    assert changed is True
    assert _stored_rows(postgres_db_real)[(_utc_date(0), "alice", "agent-1", "", "")]["runs_count"] == 2


def test_get_os_metrics_state_changes_only_when_a_rebuild_writes_or_deletes(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure get_os_metrics_state is the same again until a rebuild writes or deletes a row"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.refresh_os_metrics()

    updated_at, state_hash = postgres_db_real.get_os_metrics_state()
    assert updated_at is not None
    assert state_hash

    # Nothing new: no row is written, so the state is the same
    postgres_db_real.refresh_os_metrics()
    assert postgres_db_real.get_os_metrics_state() == (updated_at, state_hash)

    # A window that ends on a day still open is told the whole state, one that ends on a completed day the
    # state of the completed days
    assert postgres_db_real.get_os_metrics_state(_utc_date(1)) == (updated_at, state_hash)
    completed_updated_at, completed_state_hash = postgres_db_real.get_os_metrics_state(_utc_date(2))
    assert completed_updated_at is not None
    assert completed_state_hash

    # The only session of today is gone: its row is deleted and none is written, and the state still moves
    assert postgres_db_real.delete_session(sample_sessions_for_os_metrics[4].session_id) is True
    postgres_db_real.refresh_os_metrics()
    _, latest_state_hash = postgres_db_real.get_os_metrics_state()
    assert latest_state_hash != state_hash
    # The state of the completed days is not moved by a day still open
    assert postgres_db_real.get_os_metrics_state(_utc_date(2)) == (completed_updated_at, completed_state_hash)


def test_refresh_os_metrics_after_a_delete_moves_the_day(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild that only deletes a row reports the change, moves the day's updated_at and keeps its totals"""
    alice_today_session = sample_sessions_for_os_metrics[4]
    bob_today_session = AgentSession(
        session_id="bob_today_session",
        agent_id="agent-1",
        user_id="bob",
        runs=[
            RunOutput(
                run_id="bob_today_run",
                agent_id="agent-1",
                user_id="bob",
                status=RunStatus.completed,
                messages=[],
                created_at=alice_today_session.created_at,
            )
        ],
        created_at=alice_today_session.created_at,
        updated_at=alice_today_session.created_at,
    )
    for session in [*sample_sessions_for_os_metrics, bob_today_session]:
        _persist(postgres_db_real, session)
    postgres_db_real.refresh_os_metrics()

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().values(updated_at=1))

    assert postgres_db_real.delete_session("bob_today_session") is True
    previous_updated_at, latest_updated_at, changed = postgres_db_real.refresh_os_metrics()
    assert previous_updated_at == 1
    assert latest_updated_at != 1
    assert changed is True

    # Bob's row is gone, and alice's row of the day is rewritten, so a read of the day reports the new time
    today = _utc_date(0)
    metrics, read_updated_at = postgres_db_real.get_os_metrics(
        starting_date=today, ending_date=today, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [{"date": today, "sessions_count": 1, "runs_count": 1}]
    assert read_updated_at == latest_updated_at
    stored_rows = _stored_rows(postgres_db_real)
    assert all(row["updated_at"] == 1 for row in stored_rows.values() if row["date"] != today)


def test_calculate_os_metrics_reads_nested_run_ids_in_chunks(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a day with more nested runs than one statement is given finds every one stored as a run of its own"""
    monkeypatch.setattr("agno.db.postgres.postgres.OS_METRICS_IN_LIST_LIMIT", 2)
    base_time = _noon_utc(2)
    member_runs = [
        RunOutput(
            run_id=f"member_run_{index}",
            agent_id="agent-2",
            user_id="bob",
            parent_run_id="team_run",
            status=RunStatus.completed,
            model="gpt-5",
            model_provider="OpenAI",
            metrics=_run_metrics(10, 0),
            messages=[],
            created_at=base_time,
        )
        for index in range(5)
    ]
    team_session = TeamSession(
        session_id="team_session",
        team_id="team-1",
        user_id="bob",
        runs=[
            TeamRunOutput(
                run_id="team_run",
                team_id="team-1",
                user_id="bob",
                status=RunStatus.completed,
                member_responses=member_runs,
                created_at=base_time,
            ),
            *member_runs,
        ],
        created_at=base_time,
        updated_at=base_time,
    )
    _persist(postgres_db_real, team_session)
    postgres_db_real.calculate_os_metrics()

    # Every member run is stored as a run of its own, so none is counted again from the team run
    past_day = _utc_date(2)
    stored_rows = _stored_rows(postgres_db_real)
    assert stored_rows[(past_day, "bob", "", "team-1", "")]["token_metrics"] == {}
    assert stored_rows[(past_day, "bob", "agent-2", "", "")]["runs_count"] == 5
    assert stored_rows[(past_day, "bob", "agent-2", "", "")]["token_metrics"]["input_tokens"] == 50
    total_row = _stored_total_rows(postgres_db_real)[(past_day, "daily_total", "", "", "", "")]
    assert total_row["token_metrics"]["input_tokens"] == 50


def test_calculate_os_metrics_stores_each_day_as_it_is_calculated(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a day that fails to calculate leaves the days before it stored, and the next rebuild writes the rest"""
    for days_ago in [3, 2, 1, 0]:
        _persist(postgres_db_real, _session_on(_utc_date(days_ago), f"alice_{days_ago}_days_ago", "alice"))

    def _fail_two_days_ago(date_to_process, *args):
        if date_to_process == _utc_date(2):
            raise RuntimeError("Two days ago cannot be calculated")
        return calculate_date_os_metrics(date_to_process, *args)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.postgres.calculate_date_os_metrics", _fail_two_days_ago)
        with pytest.raises(RuntimeError):
            postgres_db_real.calculate_os_metrics()
    assert {row_id[0] for row_id in _stored_rows(postgres_db_real)} == {_utc_date(3)}

    postgres_db_real.calculate_os_metrics()
    assert {row_id[0] for row_id in _stored_rows(postgres_db_real)} == {
        _utc_date(3),
        _utc_date(2),
        _utc_date(1),
        _utc_date(0),
    }


def test_calculate_os_metrics_counts_nested_runs_at_every_depth(postgres_db_real: PostgresDb):
    """Ensure the runs nested inside a run are counted at every depth, from only what is read of them"""
    inner_member = RunOutput(
        run_id="nested_inner_member",
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(2, 1),
        messages=[_assistant_message(0.4)],
    )
    inner_team = TeamRunOutput(
        run_id="nested_inner_team",
        team_id="inner-team",
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(3, 1),
        messages=[_assistant_message(0.5)],
        member_responses=[inner_member],
    )
    member = RunOutput(
        run_id="nested_member",
        agent_id="agent-2",
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(4, 2),
        messages=[
            Message(role="assistant", content="Earlier", from_history=True, metrics=MessageMetrics(duration=9.9)),
            _assistant_message(0.6),
        ],
    )
    session = TeamSession(
        session_id="nested_session",
        team_id="team-1",
        user_id="alice",
        runs=[
            TeamRunOutput(
                run_id="nested_team_run",
                team_id="team-1",
                user_id="alice",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(10, 5, duration=2.0),
                messages=[_assistant_message(1.2)],
                member_responses=[member, inner_team],
                created_at=_noon_utc(2),
            )
        ],
        created_at=_noon_utc(2),
    )
    _persist(postgres_db_real, session)

    runs_table = postgres_db_real._get_table("runs")
    with postgres_db_real.Session() as sess:
        result = sess.execute(build_os_metrics_runs_query(runs_table, _noon_utc(2), _noon_utc(2) + 1))
        (run,) = result.fetchall()
    assert [(nested_run["depth"], nested_run["run_id"]) for nested_run in run.nested_runs] == [
        (1, "nested_member"),
        (1, "nested_inner_team"),
        (2, "nested_inner_member"),
    ]
    assert all("messages" not in nested_run for nested_run in run.nested_runs)
    assert [nested_run["call_durations"] for nested_run in run.nested_runs] == [[0.6], [0.5], [0.4]]

    postgres_db_real.calculate_os_metrics()

    row = _stored_rows(postgres_db_real)[(_utc_date(2), "alice", "", "team-1", "")]
    assert row["token_metrics"] == {"input_tokens": 19, "output_tokens": 9, "total_tokens": 28}
    assert row["duration_metrics"]["model_calls_count"] == 4
    assert row["duration_metrics"]["total_model_call_ms"] == 2700
    assert row["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2, "team_id": "inner-team"},
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1, "team_id": "team-1"},
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1, "agent_id": "agent-2"},
    ]
