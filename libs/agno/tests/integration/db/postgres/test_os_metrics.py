"""Integration tests for the OS Metrics related methods of the PostgresDb class"""

import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

import pytest
from sqlalchemy import inspect, select, text

from agno.db.postgres.postgres import PostgresDb
from agno.db.postgres.utils import build_os_metrics_runs_query
from agno.db.utils import (
    calculate_date_os_metrics,
    merge_os_metrics_totals,
    os_metrics_month_end,
    resolve_os_metrics_fields,
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
            for table_type in ["os_metrics", "os_metrics_totals", "runs", "sessions"]:
                table = postgres_db_real._get_table(table_type, create_table_if_not_found=True)
                session.execute(table.delete())
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


def _utc_date(days_ago: int) -> date:
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


def _run_metrics(
    input_tokens: int, output_tokens: int, duration: Optional[float] = None, time_to_first_token: Optional[float] = None
) -> RunMetrics:
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
    """Every day row of agno_os_metrics, keyed by (date, user_id, component_type, component_id).

    The month rows are left out: see ``_stored_month_rows``.
    """
    table = db._get_table("os_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in sess.execute(select(table).where(table.c.aggregation_period == "daily")).fetchall()
        }


def _stored_month_rows(db: PostgresDb) -> Dict[tuple, Dict]:
    """Every month row of agno_os_metrics, keyed as in ``_stored_rows``."""
    table = db._get_table("os_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in sess.execute(select(table).where(table.c.aggregation_period == "monthly")).fetchall()
        }


def _stored_totals_rows(db: PostgresDb) -> Dict[tuple, Dict]:
    """Every row of agno_os_metrics_totals, keyed by (aggregation_period, date)."""
    table = db._get_table("os_metrics_totals", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.aggregation_period, row.date): dict(row._mapping) for row in sess.execute(select(table)).fetchall()
        }


def _month_start(months_ago: int) -> date:
    """The first day of the calendar month ``months_ago`` months back."""
    month_start = datetime.now(timezone.utc).date().replace(day=1)
    for _ in range(months_ago):
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    return month_start


def _session_at(created_at: int, session_id: str, user_id: Optional[str], input_tokens: int = 10) -> AgentSession:
    """An agent session created at the given time, with one completed run."""
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


def _session_on(day: date, session_id: str, user_id: Optional[str], input_tokens: int = 10) -> AgentSession:
    """An agent session created at midday UTC of the given day, with one completed run."""
    created_at = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
    return _session_at(created_at, session_id, user_id, input_tokens)


def _completed_months() -> set:
    """The first day of every month of the multi-month sessions whose last day is completed by now."""
    month_starts = {_month_start(3), _month_start(2), _month_start(1)}
    return {month_start for month_start in month_starts if os_metrics_month_end(month_start) <= _utc_date(2)}


def _sessions_counts(db: PostgresDb, day: date, user_id: Optional[str]) -> List[int]:
    """The sessions_count of each day get_os_metrics returns for the given day, for every owner or one."""
    metrics, _ = db.get_os_metrics(starting_date=day, ending_date=day, user_id=user_id, fields=["sessions_count"])
    return [day_totals["sessions_count"] for day_totals in metrics]


def _total_sessions_count(db: PostgresDb, starting_date: date, ending_date: date, user_id: Optional[str] = None) -> int:
    """The sessions_count get_os_metrics_totals returns for the date range, for every owner or one."""
    totals, _ = db.get_os_metrics_totals(
        starting_date=starting_date, ending_date=ending_date, user_id=user_id, fields=["sessions_count"]
    )
    return totals["sessions_count"]


@pytest.fixture
def sample_sessions_for_os_metrics() -> List[Union[AgentSession, TeamSession]]:
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
    ("alice", "agent", "agent-1"),
    ("bob", "agent", "agent-1"),
    ("bob", "team", "team-1"),
    ("bob", "agent", "agent-2"),
    ("", "agent", "agent-1"),
]


def test_os_metrics_table_creation(postgres_db_real: PostgresDb):
    """Ensure both OS metrics tables are created with their columns, primary keys and indexes"""
    os_metrics_table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    totals_table = postgres_db_real._get_table("os_metrics_totals", create_table_if_not_found=True)

    assert os_metrics_table.name == postgres_db_real.os_metrics_table_name
    assert totals_table.name == postgres_db_real.os_metrics_totals_table_name
    assert os_metrics_table.schema == totals_table.schema == postgres_db_real.db_schema

    assert [col.name for col in os_metrics_table.columns] == [
        "aggregation_period",
        "date",
        "user_id",
        "component_type",
        "component_id",
        "parent_component_id",
        "sessions_count",
        "runs_count",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "duration_runs_count",
        "total_duration_ms",
        "max_duration_ms",
        "time_to_first_token_runs_count",
        "total_time_to_first_token_ms",
        "max_time_to_first_token_ms",
        "model_calls_count",
        "total_model_call_ms",
        "max_model_call_ms",
        "buckets_version",
        "status_metrics",
        "additional_token_metrics",
        "duration_buckets",
        "time_to_first_token_buckets",
        "model_call_buckets",
        "model_metrics",
        "additional_metrics",
        "created_at",
        "updated_at",
    ]
    assert set(col.name for col in totals_table.columns) == {
        "aggregation_period",
        "date",
        "completed",
        "version",
        "sessions_count",
        "runs_count",
        "status_metrics",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "additional_token_metrics",
        "duration_runs_count",
        "total_duration_ms",
        "max_duration_ms",
        "time_to_first_token_runs_count",
        "total_time_to_first_token_ms",
        "max_time_to_first_token_ms",
        "model_calls_count",
        "total_model_call_ms",
        "max_model_call_ms",
        "duration_buckets",
        "time_to_first_token_buckets",
        "model_call_buckets",
        "buckets_version",
        "model_metrics",
        "additional_metrics",
        "created_at",
        "updated_at",
    }

    inspector = inspect(postgres_db_real.db_engine)
    assert inspector.get_pk_constraint(os_metrics_table.name, schema=os_metrics_table.schema)[
        "constrained_columns"
    ] == [
        "aggregation_period",
        "date",
        "user_id",
        "component_type",
        "component_id",
        "parent_component_id",
    ]
    assert inspector.get_pk_constraint(totals_table.name, schema=totals_table.schema)["constrained_columns"] == [
        "aggregation_period",
        "date",
    ]
    indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes(os_metrics_table.name, schema=os_metrics_table.schema)
    }
    assert indexes[f"idx_{os_metrics_table.name}_user_id_aggregation_period_date"] == [
        "user_id",
        "aggregation_period",
        "date",
    ]


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
        assert _stored_totals_rows(postgres_db_real) == {}
        # A skipped rebuild does not count as a refresh, so the next read tries again
        assert postgres_db_real._os_metrics_refreshed_at == 0.0

    # Nobody holds the lock any more, so the same call rebuilds
    result = postgres_db_real._calculate_os_metrics(wait_for_rebuild=False)
    assert result is not None
    assert len(_stored_rows(postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


def test_calculate_os_metrics_skips_messages_carried_over_from_history(postgres_db_real: PostgresDb):
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

    row = _stored_rows(postgres_db_real)[(_utc_date(2), "alice", "agent", "agent-1")]
    assert row["model_calls_count"] == 1
    assert row["total_model_call_ms"] == 1200
    assert row["model_call_buckets"] == {"le_1200": 1}


def test_calculate_os_metrics(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure calculate_os_metrics writes one row per owner and component for each day"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)

    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    # The past day's rows and today's row
    assert len(result) == len(PAST_DAY_ROW_KEYS) + 1

    past_day = _utc_date(2)
    today = _utc_date(0)
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == len(PAST_DAY_ROW_KEYS) + 1

    # Rows are unique by day, owner and component, so every row can be found by that key
    for key in PAST_DAY_ROW_KEYS:
        assert (past_day, *key) in stored_rows
    today_row = stored_rows[(today, "alice", "agent", "agent-1")]
    assert today_row["sessions_count"] == 1
    assert today_row["runs_count"] == 1

    alice_row = stored_rows[(past_day, "alice", "agent", "agent-1")]
    assert alice_row["aggregation_period"] == "daily"
    assert alice_row["date"] == past_day
    assert alice_row["sessions_count"] == 1
    assert alice_row["runs_count"] == 2
    assert alice_row["status_metrics"] == {COMPLETED: 1, ERROR: 1}
    assert (alice_row["input_tokens"], alice_row["output_tokens"], alice_row["total_tokens"]) == (110, 50, 160)
    # No rarer token kind was reported, and no zero key is stored
    assert alice_row["additional_token_metrics"] == {}
    assert (alice_row["duration_runs_count"], alice_row["total_duration_ms"], alice_row["max_duration_ms"]) == (
        1,
        2000,
        2000,
    )
    assert alice_row["duration_buckets"] == {"le_2000": 1}
    assert (
        alice_row["time_to_first_token_runs_count"],
        alice_row["total_time_to_first_token_ms"],
        alice_row["max_time_to_first_token_ms"],
    ) == (1, 500, 500)
    assert alice_row["time_to_first_token_buckets"] == {"le_500": 1}
    assert (alice_row["model_calls_count"], alice_row["total_model_call_ms"], alice_row["max_model_call_ms"]) == (
        1,
        1500,
        1500,
    )
    assert alice_row["model_call_buckets"] == {"le_1500": 1}
    assert alice_row["buckets_version"] == 1
    # The error run reported no details, so only the completed run's model is counted
    assert alice_row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 1}]
    assert alice_row["created_at"] is not None
    assert alice_row["updated_at"] is not None

    # The team run counts under the team, its member's run under the member agent
    team_row = stored_rows[(past_day, "bob", "team", "team-1")]
    assert team_row["sessions_count"] == 1
    assert team_row["runs_count"] == 1
    member_row = stored_rows[(past_day, "bob", "agent", "agent-2")]
    assert member_row["sessions_count"] == 0
    assert member_row["runs_count"] == 1
    assert (member_row["input_tokens"], member_row["output_tokens"], member_row["total_tokens"]) == (40, 10, 50)

    unowned_row = stored_rows[(past_day, "", "agent", "agent-1")]
    assert unowned_row["sessions_count"] == 1
    assert unowned_row["runs_count"] == 1


def test_calculate_os_metrics_writes_a_total_row_for_every_day(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure every day gets one total row for every owner, a day without traffic included"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    yesterday = _utc_date(1)
    today = _utc_date(0)
    totals_rows = _stored_totals_rows(postgres_db_real)
    assert set(totals_rows) == {("daily", past_day), ("daily", yesterday), ("daily", today)}

    day_row = totals_rows[("daily", past_day)]
    assert day_row["sessions_count"] == 4
    assert day_row["runs_count"] == 6
    assert day_row["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert (day_row["input_tokens"], day_row["output_tokens"], day_row["total_tokens"]) == (385, 185, 570)
    assert day_row["duration_runs_count"] == 4
    assert day_row["max_duration_ms"] == 4000
    assert day_row["duration_buckets"] == {"le_1000": 1, "le_2000": 1, "le_3000": 1, "le_4000": 1}
    assert day_row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 5}]
    assert day_row["completed"] is True
    assert day_row["version"] == 1

    # Yesterday has no traffic and is still open; today is open too
    yesterday_row = totals_rows[("daily", yesterday)]
    assert (yesterday_row["sessions_count"], yesterday_row["runs_count"], yesterday_row["max_duration_ms"]) == (
        0,
        0,
        None,
    )
    assert yesterday_row["completed"] is False
    assert totals_rows[("daily", today)]["sessions_count"] == 1
    assert totals_rows[("daily", today)]["completed"] is False


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
    alice_today_row_id = (today, "alice", "agent", "agent-1")
    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    assert [(row["date"], row["user_id"], row["component_type"], row["component_id"]) for row in result] == [
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
    bob_today_row_id = (today, "bob", "agent", "agent-1")
    assert bob_today_row_id in _stored_rows(postgres_db_real)

    assert postgres_db_real.delete_session("bob_today_session") is True
    postgres_db_real.calculate_os_metrics()
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert bob_today_row_id not in stored_rows


def test_get_os_metrics_by_date(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals each day, for every owner from the total rows or for one owner from its rows"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    yesterday = _utc_date(1)
    today = _utc_date(0)

    # Every owner: one dict per day, oldest first, a day without traffic included, with every field
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today)
    assert [m["date"] for m in metrics] == [past_day, yesterday, today]
    past_day_totals = metrics[0]
    assert set(past_day_totals) == {"date", *resolve_os_metrics_fields(None)}
    assert past_day_totals["sessions_count"] == 4
    assert past_day_totals["runs_count"] == 6
    assert past_day_totals["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert (past_day_totals["input_tokens"], past_day_totals["output_tokens"], past_day_totals["total_tokens"]) == (
        385,
        185,
        570,
    )
    assert (
        past_day_totals["duration_runs_count"],
        past_day_totals["total_duration_ms"],
        past_day_totals["max_duration_ms"],
    ) == (4, 10000, 4000)
    assert (
        past_day_totals["time_to_first_token_runs_count"],
        past_day_totals["total_time_to_first_token_ms"],
        past_day_totals["max_time_to_first_token_ms"],
    ) == (
        2,
        1500,
        1000,
    )
    assert (
        past_day_totals["model_calls_count"],
        past_day_totals["total_model_call_ms"],
        past_day_totals["max_model_call_ms"],
    ) == (2, 4000, 2500)
    assert past_day_totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 5}]
    assert metrics[1]["sessions_count"] == 0
    assert metrics[1]["max_duration_ms"] is None
    assert metrics[2]["sessions_count"] == 1
    assert metrics[2]["runs_count"] == 1

    # The latest updated_at of the window is the one returned
    totals_rows = _stored_totals_rows(postgres_db_real)
    assert latest_updated_at == max(row["updated_at"] for row in totals_rows.values())

    # One owner: only bob's rows are summed, on the days bob has rows
    metrics, latest_updated_at = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=today, user_id="bob"
    )
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 2
    assert metrics[0]["runs_count"] == 3
    assert (metrics[0]["input_tokens"], metrics[0]["output_tokens"], metrics[0]["total_tokens"]) == (270, 130, 400)
    stored_rows = _stored_rows(postgres_db_real)
    assert latest_updated_at == max(row["updated_at"] for row in stored_rows.values() if row["user_id"] == "bob")

    # The empty owner: only the unowned rows
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, user_id="")
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 1
    assert metrics[0]["runs_count"] == 1
    assert (metrics[0]["input_tokens"], metrics[0]["output_tokens"], metrics[0]["total_tokens"]) == (5, 5, 10)


def test_get_os_metrics_fields(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics returns only the fields asked for"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=past_day, fields=["total_duration_ms", "max_duration_ms"]
    )
    assert metrics == [{"date": past_day, "total_duration_ms": 10000, "max_duration_ms": 4000}]

    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day,
        ending_date=past_day,
        fields=["duration_buckets", "time_to_first_token_buckets", "model_call_buckets"],
    )
    assert metrics == [
        {
            "date": past_day,
            "duration_buckets": {"le_1000": 1, "le_2000": 1, "le_3000": 1, "le_4000": 1},
            "time_to_first_token_buckets": {"le_500": 1, "le_1000": 1},
            "model_call_buckets": {"le_1500": 1, "le_2500": 1},
        }
    ]

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
    assert metrics == [
        {"date": past_day, "sessions_count": 4},
        {"date": _utc_date(1), "sessions_count": 0},
        {"date": today, "sessions_count": 1},
    ]
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
    # Each day's row
    assert len(result) == 2

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


def test_get_os_metrics_reads_every_owner_from_the_total_rows(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a read equals the sum of the rows, with every owner read from the total rows and one owner from its"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    today = _utc_date(0)
    days = [past_day, _utc_date(1), today]
    stored_rows = list(_stored_rows(postgres_db_real).values())
    fields = resolve_os_metrics_fields(None)

    # Every owner, then one owner: the same totals as the rows add up to
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today)
    assert metrics == [
        {"date": day, **merge_os_metrics_totals([row for row in stored_rows if row["date"] == day], fields)}
        for day in days
    ]
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, user_id="bob")
    assert metrics == [
        {"date": past_day, **merge_os_metrics_totals([row for row in stored_rows if row["user_id"] == "bob"], fields)}
    ]

    # Change every row: every owner is still read from the total rows, one owner from that owner's rows
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().values(sessions_count=50))
    metrics, _ = postgres_db_real.get_os_metrics(starting_date=past_day, ending_date=today, fields=["sessions_count"])
    assert [day_totals["sessions_count"] for day_totals in metrics] == [4, 0, 1]
    # bob has three rows on the past day
    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=past_day, ending_date=today, user_id="bob", fields=["sessions_count"]
    )
    assert metrics == [{"date": past_day, "sessions_count": 150}]


def test_get_os_metrics_never_reads_a_total_row_for_one_owner(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure one owner's read uses only that owner's rows, and the empty owner's never the total row"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    past_day = _utc_date(2)
    totals_table = postgres_db_real._get_table("os_metrics_totals", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(totals_table.update().where(totals_table.c.date == past_day).values(sessions_count=1000))

    assert _sessions_counts(postgres_db_real, past_day, None) == [1000]
    assert _sessions_counts(postgres_db_real, past_day, "alice") == [1]
    assert _sessions_counts(postgres_db_real, past_day, "bob") == [2]
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
    month_rows = _stored_month_rows(postgres_db_real)
    assert set(month_rows) == {
        (first_month, "", "agent", "agent-1"),
        (first_month, "alice", "agent", "agent-1"),
        (first_month, "bob", "agent", "agent-1"),
        (second_month, "bob", "agent", "agent-1"),
    }
    # A month without traffic still gets its total row
    month_totals_rows = {
        key[1]: row for key, row in _stored_totals_rows(postgres_db_real).items() if key[0] == "monthly"
    }
    assert set(month_totals_rows) == _completed_months()

    month_row = month_totals_rows[first_month]
    assert month_row["sessions_count"] == 4
    assert month_row["runs_count"] == 4
    assert (month_row["input_tokens"], month_row["output_tokens"], month_row["total_tokens"]) == (165, 20, 185)
    assert month_row["duration_buckets"] == {"le_2000": 4}
    assert month_row["completed"] is True
    alice_row = month_rows[(first_month, "alice", "agent", "agent-1")]
    assert alice_row["sessions_count"] == 2
    assert alice_row["input_tokens"] == 120
    assert alice_row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}]
    assert month_rows[(first_month, "", "agent", "agent-1")]["sessions_count"] == 1
    assert month_totals_rows[second_month]["sessions_count"] == 1

    # The month rows are no rows of the first day of their month: a rebuild leaves them alone
    postgres_db_real.calculate_os_metrics()
    assert _stored_month_rows(postgres_db_real) == month_rows


def test_calculate_os_metrics_calculates_a_month_a_rebuild_missed(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a completed month without month rows gets them from the next rebuild, without its days rebuilt"""
    for session in sample_multi_month_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    table = postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    totals_table = postgres_db_real._get_table("os_metrics_totals", create_table_if_not_found=True)
    month_rows = _stored_month_rows(postgres_db_real)

    # The first month loses its month rows
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.delete().where(table.c.aggregation_period == "monthly", table.c.date == first_month))
        sess.execute(
            totals_table.delete().where(
                totals_table.c.aggregation_period == "monthly", totals_table.c.date == first_month
            )
        )

    result = postgres_db_real.calculate_os_metrics()
    assert result is not None
    assert {row["date"] for row in result} == {_utc_date(0)}
    assert set(_stored_month_rows(postgres_db_real)) == set(month_rows)
    assert ("monthly", first_month) in _stored_totals_rows(postgres_db_real)


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
            totals, _ = postgres_db_real.get_os_metrics_totals(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            metrics, _ = postgres_db_real.get_os_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            assert totals == merge_os_metrics_totals(metrics, fields)

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
    totals_table = postgres_db_real._get_table("os_metrics_totals", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            totals_table.update()
            .where(totals_table.c.aggregation_period == "monthly", totals_table.c.date == first_month)
            .values(sessions_count=1000)
        )
        sess.execute(
            table.update()
            .where(table.c.aggregation_period == "monthly", table.c.date == first_month, table.c.user_id == "bob")
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
    # One owner's month comes from that owner's month rows
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1), "alice") == 2
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1), "bob") == 500
    assert _total_sessions_count(postgres_db_real, first_month, second_month - timedelta(days=1), "") == 1
    # The read of each day never uses a month row: every day of the month, the days without traffic included
    metrics, _ = postgres_db_real.get_os_metrics(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), fields=["sessions_count"]
    )
    assert len(metrics) == (second_month - first_month).days
    assert [day_totals for day_totals in metrics if day_totals["sessions_count"]] == [
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

    # Nothing new: no row is written, and the tables were last updated when they were before
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
    assert _stored_rows(postgres_db_real)[(_utc_date(0), "alice", "agent", "agent-1")]["runs_count"] == 2


def test_refresh_os_metrics_with_nothing_new_leaves_every_version(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a rebuild that writes nothing moves no version"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.refresh_os_metrics()

    versions = postgres_db_real.get_os_metrics_versions(_utc_date(2), _utc_date(0))
    assert versions == {f"daily {_utc_date(days_ago).isoformat()}": 1 for days_ago in (2, 1, 0)}

    _, _, changed = postgres_db_real.refresh_os_metrics()
    assert changed is False
    assert postgres_db_real.get_os_metrics_versions(_utc_date(2), _utc_date(0)) == versions


def test_get_os_metrics_versions_move_only_for_the_day_that_changed(
    postgres_db_real: PostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a rebuild that writes or deletes a day's rows moves that day's version and no other"""
    for session in sample_sessions_for_os_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.refresh_os_metrics()
    versions = postgres_db_real.get_os_metrics_versions(_utc_date(2), _utc_date(0))
    today_key = f"daily {_utc_date(0).isoformat()}"

    # The only session of today is gone: its row is deleted and none is written, and today's version still moves
    assert postgres_db_real.delete_session(sample_sessions_for_os_metrics[4].session_id) is True
    postgres_db_real.refresh_os_metrics()
    assert postgres_db_real.get_os_metrics_versions(_utc_date(2), _utc_date(0)) == {
        **versions,
        today_key: versions[today_key] + 1,
    }
    # Only the total rows inside the date range are returned
    assert postgres_db_real.get_os_metrics_versions(_utc_date(1), _utc_date(1)) == {
        f"daily {_utc_date(1).isoformat()}": 1
    }


def test_refresh_os_metrics_counts_a_late_run_of_yesterday(postgres_db_real: PostgresDb):
    """Ensure a run started before midnight and stored after a rebuild of today is counted on yesterday"""
    _persist(postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    postgres_db_real.refresh_os_metrics()
    versions = postgres_db_real.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    yesterday_key = f"daily {_utc_date(1).isoformat()}"
    assert versions[yesterday_key] == 1
    assert _stored_totals_rows(postgres_db_real)[("daily", _utc_date(1))]["runs_count"] == 0

    # Started at 23:59 yesterday, stored now
    yesterday = _utc_date(1)
    late_created_at = int(
        datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, tzinfo=timezone.utc).timestamp()
    )
    _persist(postgres_db_real, _session_at(late_created_at, "bob_late", "bob"))
    _, _, changed = postgres_db_real.refresh_os_metrics()
    assert changed is True

    assert _stored_totals_rows(postgres_db_real)[("daily", yesterday)]["runs_count"] == 1
    assert (yesterday, "bob", "agent", "agent-1") in _stored_rows(postgres_db_real)
    assert postgres_db_real.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == {
        **versions,
        yesterday_key: 2,
    }


def test_calculate_os_metrics_never_rebuilds_a_completed_empty_day(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a day without traffic gets a completed total row, and a later rebuild starts after it"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_3_days_ago", "alice"))
    _persist(postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    postgres_db_real.calculate_os_metrics()

    empty_day_row = _stored_totals_rows(postgres_db_real)[("daily", _utc_date(2))]
    assert (empty_day_row["sessions_count"], empty_day_row["runs_count"]) == (0, 0)
    assert empty_day_row["completed"] is True

    calculated_days = []

    def _calculate(date_to_process, *args):
        calculated_days.append(date_to_process)
        return calculate_date_os_metrics(date_to_process, *args)

    monkeypatch.setattr("agno.db.postgres.postgres.calculate_date_os_metrics", _calculate)
    postgres_db_real.calculate_os_metrics()
    assert calculated_days == [_utc_date(1), _utc_date(0)]


def test_refresh_os_metrics_after_a_delete_moves_the_day(postgres_db_real: PostgresDb, sample_sessions_for_os_metrics):
    """Ensure a rebuild that only deletes a row reports the change, moves the day's total row and keeps its totals"""
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
    with postgres_db_real.Session() as sess, sess.begin():
        for table_type in ("os_metrics", "os_metrics_totals"):
            table = postgres_db_real._get_table(table_type, create_table_if_not_found=True)
            sess.execute(table.update().values(updated_at=1))

    assert postgres_db_real.delete_session("bob_today_session") is True
    previous_updated_at, latest_updated_at, changed = postgres_db_real.refresh_os_metrics()
    assert previous_updated_at == 1
    assert latest_updated_at != 1
    assert changed is True

    # Bob's row is gone, and today's total row is rewritten, so a read of the day reports the new time
    today = _utc_date(0)
    metrics, read_updated_at = postgres_db_real.get_os_metrics(
        starting_date=today, ending_date=today, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [{"date": today, "sessions_count": 1, "runs_count": 1}]
    assert read_updated_at == latest_updated_at
    totals_rows = _stored_totals_rows(postgres_db_real)
    assert all(row["updated_at"] == 1 for key, row in totals_rows.items() if key[1] != today)


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
    assert stored_rows[(past_day, "bob", "team", "team-1")]["input_tokens"] == 0
    assert stored_rows[(past_day, "bob", "agent", "agent-2")]["runs_count"] == 5
    assert stored_rows[(past_day, "bob", "agent", "agent-2")]["input_tokens"] == 50
    assert _stored_totals_rows(postgres_db_real)[("daily", past_day)]["input_tokens"] == 50


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
    assert set(_stored_totals_rows(postgres_db_real)) == {("daily", _utc_date(3))}

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

    # The nested runs are no runs of their own, so their tokens and calls are on the row of the team run
    row = _stored_rows(postgres_db_real)[(_utc_date(2), "alice", "team", "team-1")]
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (19, 9, 28)
    assert row["model_calls_count"] == 4
    assert row["total_model_call_ms"] == 2700
    assert row["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4}]


def test_calculate_os_metrics_skips_a_refresh_with_nothing_new(postgres_db_real: PostgresDb):
    """A refresh that does not wait skips the rebuild while no session or run changed, and rebuilds after one did"""
    _persist(postgres_db_real, _session_on(_utc_date(0), "skipped_session", "alice"))
    # Written a minute ago, so no write shares the current second
    with postgres_db_real.Session() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = postgres_db_real._get_table(table_type)
            sess.execute(table.update().values(updated_at=int(time.time()) - 60))

    assert postgres_db_real._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert postgres_db_real._calculate_os_metrics(wait_for_rebuild=False) is None

    _persist(postgres_db_real, _session_on(_utc_date(0), "new_session", "alice"))
    assert postgres_db_real._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert _sessions_counts(postgres_db_real, _utc_date(0), None) == [2]


def test_get_os_metrics_versions_is_none_while_today_is_unbuilt(postgres_db_real: PostgresDb):
    """A database with sessions today and no total row for today has no versions, so a read skips it"""
    _persist(postgres_db_real, _session_on(_utc_date(0), "unbuilt_session", "alice"))
    # Written a minute ago, so the refresh below keeps a fingerprint that a refresh with nothing new would match
    with postgres_db_real.Session() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = postgres_db_real._get_table(table_type)
            sess.execute(table.update().values(updated_at=int(time.time()) - 60))
    postgres_db_real.calculate_os_metrics()
    totals_table = postgres_db_real._get_table("os_metrics_totals")
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(totals_table.delete().where(totals_table.c.date == _utc_date(0)))

    # Inside the refresh throttle, as between a refresh and the rebuild of today
    postgres_db_real._os_metrics_refreshed_at = time.time()
    assert postgres_db_real.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is None

    # No session or run changed, but the unbuilt day makes the next refresh rebuild it
    postgres_db_real._os_metrics_refreshed_at = 0.0
    versions = postgres_db_real.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    assert f"daily {_utc_date(0).isoformat()}" in versions
