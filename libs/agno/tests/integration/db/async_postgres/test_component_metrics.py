"""Integration tests for the component metrics related methods of the AsyncPostgresDb class"""

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text

from agno.db.base import SessionType
from agno.db.postgres import AsyncPostgresDb
from agno.db.postgres.schemas import (
    AGGREGATE_METRICS_TABLE_SCHEMA,
    COMPONENT_METRICS_TABLE_SCHEMA,
    METRICS_REFRESHES_TABLE_SCHEMA,
)
from agno.db.utils import (
    AGGREGATE_METRICS_COUNT_COLUMNS,
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_DETAILS_FIELDS,
    METRICS_TOKEN_FIELDS,
    resolve_metrics_fields,
)
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics, ToolCallMetrics
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup_component_metrics_sessions_and_runs(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up component metrics, session and run rows after each test"""
    yield

    for table_type in ["component_metrics", "aggregate_metrics", "metrics_refreshes", "metrics", "runs", "sessions"]:
        try:
            table = await async_postgres_db_real._get_table(table_type, create_table_if_not_found=True)
            async with async_postgres_db_real.async_session_factory() as session:
                await session.execute(table.delete())
                await session.commit()
        except Exception:
            pass  # Ignore cleanup errors for this table


@pytest_asyncio.fixture
async def legacy_runs_column(async_postgres_db_real: AsyncPostgresDb):
    """Fixture adding the sessions table's legacy runs column, and dropping it after the test"""
    schema_version = await async_postgres_db_real.get_latest_schema_version(async_postgres_db_real.session_table_name)
    await async_postgres_db_real._get_table("sessions", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN runs JSONB"))
    yield

    await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, schema_version)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(text("ALTER TABLE test_schema.test_sessions DROP COLUMN runs"))


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back.

    The sessions below are laid an hour apart from this point, so every one of them lands in
    the UTC day ``days_ago`` days back whatever the current time of day is.
    """
    day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day a component metrics row is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


async def _persist(db: AsyncPostgresDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table.

    ``upsert_session`` stopped writing the runs column when runs were normalised out, so a
    component metrics test that only called it would count no runs at all.
    """
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


async def _store_legacy_runs(db: AsyncPostgresDb, runs: List[Dict]) -> AsyncPostgresDb:
    """Keep the runs in the sessions table's legacy runs column, and return a new instance that reads them.

    The legacy column is read only before the v3.0.0 migration is stamped.
    """
    async with db.async_session_factory() as sess, sess.begin():
        await sess.execute(
            text("UPDATE test_schema.test_sessions SET runs = CAST(:runs AS JSONB)"), {"runs": json.dumps(runs)}
        )
    await db.upsert_schema_version(db.session_table_name, "2.5.0")
    # A new instance, so the sessions table is read with its legacy column
    return AsyncPostgresDb(db_engine=db.db_engine, db_schema="test_schema", session_table="test_sessions")


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


async def _stored_rows(db: AsyncPostgresDb) -> Dict[tuple, Dict]:
    """Every row of agno_component_metrics, keyed by (date, user_id, component_type, component_id)."""
    table = await db._get_table("component_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table).where(table.c.aggregation_period == "daily"))
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in result.fetchall()
        }


async def _stored_aggregate_metrics_rows(db: AsyncPostgresDb) -> Dict[tuple, Dict]:
    """Every day and month everyone row of agno_aggregate_metrics, keyed by (aggregation_period, date).

    The user rows are left out.
    """
    table = await db._get_table("aggregate_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table).where(table.c.user_id == ""))
        return {(row.aggregation_period, row.date): dict(row._mapping) for row in result.fetchall()}


def _aggregate_metrics_sessions_count(row: Dict) -> int:
    """The sessions of every type a row of agno_aggregate_metrics keeps."""
    return row["agent_sessions_count"] + row["team_sessions_count"] + row["workflow_sessions_count"]


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


@pytest.fixture
def sample_sessions_for_component_metrics() -> List[Union[AgentSession, TeamSession]]:
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


@pytest.mark.asyncio
async def test_component_metrics_table_creation(async_postgres_db_real: AsyncPostgresDb):
    """Ensure the metrics tables are created with their columns, primary keys and indexes"""
    component_metrics_table = await async_postgres_db_real._get_table(
        "component_metrics", create_table_if_not_found=True
    )
    aggregate_metrics_table = await async_postgres_db_real._get_table(
        "aggregate_metrics", create_table_if_not_found=True
    )
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)

    assert component_metrics_table.name == async_postgres_db_real.component_metrics_table_name
    assert aggregate_metrics_table.name == async_postgres_db_real.aggregate_metrics_table_name
    assert refreshes_table.name == async_postgres_db_real.metrics_refreshes_table_name
    assert component_metrics_table.schema == aggregate_metrics_table.schema == async_postgres_db_real.db_schema

    assert [col.name for col in component_metrics_table.columns] == [
        column for column in COMPONENT_METRICS_TABLE_SCHEMA if not column.startswith("_")
    ]
    assert {col.name for col in aggregate_metrics_table.columns} == set(AGGREGATE_METRICS_TABLE_SCHEMA)
    assert [col.name for col in refreshes_table.columns] == list(METRICS_REFRESHES_TABLE_SCHEMA)
    assert set(METRICS_TOKEN_FIELDS) - {*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens"} | {"token_details"} | set(
        AGGREGATE_METRICS_COUNT_COLUMNS
    ) <= set(AGGREGATE_METRICS_TABLE_SCHEMA)
    assert "sessions_count" not in AGGREGATE_METRICS_TABLE_SCHEMA

    async with async_postgres_db_real.db_engine.connect() as conn:
        component_metrics_pk, totals_pk, refreshes_pk, index_list = await conn.run_sync(
            lambda sync_conn: (
                inspect(sync_conn).get_pk_constraint(
                    component_metrics_table.name, schema=component_metrics_table.schema
                ),
                inspect(sync_conn).get_pk_constraint(
                    aggregate_metrics_table.name, schema=aggregate_metrics_table.schema
                ),
                inspect(sync_conn).get_pk_constraint(refreshes_table.name, schema=refreshes_table.schema),
                inspect(sync_conn).get_indexes(component_metrics_table.name, schema=component_metrics_table.schema),
            )
        )
    assert component_metrics_pk["constrained_columns"] == [
        "aggregation_period",
        "date",
        "user_id",
        "component_type",
        "component_id",
        "parent_component_id",
        "root_component_id",
    ]
    assert totals_pk["constrained_columns"] == [
        "aggregation_period",
        "date",
        "user_id",
    ]
    assert refreshes_pk["constrained_columns"] == ["id"]
    indexes = {index["name"]: index["column_names"] for index in index_list}
    assert indexes[f"idx_{component_metrics_table.name}_user_id_date"] == ["user_id", "date"]


@pytest.mark.asyncio
async def test_calculate_metrics_skips_a_rebuild_already_running(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure one process claims the metrics refresh at a time, and calculate_metrics writes nothing while another
    process holds it"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)

    # Another process is calculating: it holds the metrics refresh until it releases it
    assert await async_postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process") is not None
    assert await async_postgres_db_real._claim_metrics_refresh(refreshes_table, "second_process") is None
    assert await async_postgres_db_real.calculate_metrics() is None
    assert await _stored_rows(async_postgres_db_real) == {}
    assert await _stored_aggregate_metrics_rows(async_postgres_db_real) == {}

    # The other process stopped and released it, so the same call calculates
    await async_postgres_db_real._release_metrics_refresh(refreshes_table, "other_process", stopped=True)
    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    assert len(await _stored_rows(async_postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


@pytest.mark.asyncio
async def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column(
    async_postgres_db_real: AsyncPostgresDb, legacy_runs_column
):
    """Ensure a run not yet migrated out of the sessions table's legacy runs column is counted once, on its own day,
    and a first calculation builds a day with no session for it"""
    session = _session_on(_utc_date(6), "legacy_session", "alice")
    session.runs.extend(
        [
            RunOutput(
                run_id="legacy_only_run",
                agent_id="agent-1",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(30, 5),
                messages=[_assistant_message(0.5)],
                created_at=_noon_utc(6),
            ),
            RunOutput(
                run_id="legacy_later_run",
                agent_id="agent-1",
                user_id="alice",
                status=RunStatus.completed,
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(30, 5),
                messages=[],
                created_at=_noon_utc(4),
            ),
        ]
    )
    # The first run is in the runs table and the legacy column, the others in the legacy column only
    await async_postgres_db_real.upsert_session(session)
    await async_postgres_db_real.upsert_run(
        session.runs[0], session_id=session.session_id, user_id="alice", run_index=0
    )
    legacy_db = await _store_legacy_runs(async_postgres_db_real, [run.to_dict() for run in session.runs])
    await legacy_db.calculate_metrics()

    row = (await _stored_rows(legacy_db))[(_utc_date(6), "alice", "agent", "agent-1")]
    assert (row["sessions_count"], row["runs_count"], row["total_tokens"]) == (1, 2, 50)
    assert (row["model_calls_count"], row["total_model_call_ms"]) == (2, 2000)
    # The later run is counted on its own day, a day with no session
    assert (await _stored_aggregate_metrics_rows(legacy_db))[("daily", _utc_date(4))]["agent_runs_count"] == 1


@pytest.mark.asyncio
async def test_calculate_metrics(async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics):
    """Ensure calculate_metrics writes one row per owner and component for each day"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)

    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    # One row per owner and day: alice, bob and the unowned owner on the past day, alice today
    assert [(row["date"], row["user_id"]) for row in result] == [
        (_utc_date(2), None),
        (_utc_date(2), "alice"),
        (_utc_date(2), "bob"),
        (_utc_date(0), "alice"),
    ]

    past_day = _utc_date(2)
    today = _utc_date(0)
    stored_rows = await _stored_rows(async_postgres_db_real)
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
    # No rarer token kind was reported
    assert (alice_row["token_details"], alice_row["reasoning_tokens"]) == ({}, 0)
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
    # The error run reported no details, and its model is still counted, as agno_metrics counted it
    assert alice_row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}
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


@pytest.mark.asyncio
async def test_get_component_metrics_by_date(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure get_component_metrics totals each day, every owner from the everyone rows and one owner from its rows"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    yesterday = _utc_date(1)
    today = _utc_date(0)

    # Every owner: one dict per day, oldest first, a day without traffic included, with every field
    metrics, latest_updated_at = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today
    )
    assert [m["date"] for m in metrics] == [past_day, yesterday, today]
    past_day_totals = metrics[0]
    assert set(past_day_totals) == {"date", *resolve_metrics_fields(None)}
    assert past_day_totals["sessions_count"] == 4
    assert past_day_totals["root_runs_count"] == 5
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
    assert past_day_totals["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 6, "cost": None}
    ]
    assert metrics[1]["sessions_count"] == 0
    assert metrics[1]["max_duration_ms"] is None
    assert metrics[2]["sessions_count"] == 1
    assert metrics[2]["root_runs_count"] == 1

    # The latest updated_at of the window is the one returned
    aggregate_metrics_rows = await _stored_aggregate_metrics_rows(async_postgres_db_real)
    assert latest_updated_at == max(
        row["updated_at"]
        for (period, row_date), row in aggregate_metrics_rows.items()
        if period == "daily" and past_day <= row_date <= today
    )

    # One owner: only bob's rows are summed, on the days bob has rows
    metrics, latest_updated_at = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, user_id="bob"
    )
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 2
    # Bob's member run was started by his team run
    assert metrics[0]["root_runs_count"] == 2
    assert (metrics[0]["input_tokens"], metrics[0]["output_tokens"], metrics[0]["total_tokens"]) == (270, 130, 400)
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert latest_updated_at == max(row["updated_at"] for row in stored_rows.values() if row["user_id"] == "bob")

    # The empty owner: only the unowned rows
    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, user_id=""
    )
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 1
    assert metrics[0]["root_runs_count"] == 1
    assert (metrics[0]["input_tokens"], metrics[0]["output_tokens"], metrics[0]["total_tokens"]) == (5, 5, 10)


@pytest.fixture
def sample_multi_month_sessions_for_component_metrics() -> List[AgentSession]:
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


@pytest.mark.asyncio
async def test_calculate_metrics_writes_a_month_aggregate_metrics_row_for_a_completed_month(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure every month of a calculated day gets an aggregate metrics row, completed once its last day is"""
    for session in sample_multi_month_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    this_month = _month_start(0)
    # The month of yesterday gets its aggregate metrics row even without traffic
    month_aggregate_metrics_rows = {
        key[1]: row
        for key, row in (await _stored_aggregate_metrics_rows(async_postgres_db_real)).items()
        if key[0] == "monthly"
    }
    assert set(month_aggregate_metrics_rows) == {first_month, second_month, _utc_date(1).replace(day=1), this_month}
    assert {month_start for month_start, row in month_aggregate_metrics_rows.items() if row["completed"]} == {
        first_month,
        second_month,
    }

    month_row = month_aggregate_metrics_rows[first_month]
    assert _aggregate_metrics_sessions_count(month_row) == 4
    assert month_row["root_runs_count"] == 4
    assert (month_row["input_tokens"], month_row["output_tokens"], month_row["total_tokens"]) == (165, 20, 185)
    assert month_row["duration_buckets"] == {"le_2000": 4}
    assert month_row["completed"] is True
    alice_totals, _ = await async_postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), user_id="alice"
    )
    assert alice_totals["sessions_count"] == 2
    assert alice_totals["input_tokens"] == 120
    assert alice_totals["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2, "cost": None}
    ]
    # The runs with no user are read from their day rows
    unowned_totals, _ = await async_postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), user_id=""
    )
    assert unowned_totals["sessions_count"] == 1
    assert _aggregate_metrics_sessions_count(month_aggregate_metrics_rows[second_month]) == 1


@pytest.mark.asyncio
async def test_upsert_session_of_a_closed_day_from_a_fresh_process_is_stored(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a save that reopens a closed day is stored by a process that never loaded the aggregate metrics table"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(5), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    fresh_db = AsyncPostgresDb(
        db_engine=async_postgres_db_real.db_engine, db_schema="test_schema", session_table="test_sessions"
    )

    bob_session = _session_on(_utc_date(5), "bob_session", "bob")
    await _persist(fresh_db, bob_session)

    assert await fresh_db.get_run(bob_session.runs[0].run_id) is not None
    assert len(await fresh_db.get_sessions(session_type=SessionType.AGENT)) == 2
    assert (await _stored_aggregate_metrics_rows(async_postgres_db_real))[("daily", _utc_date(5))]["completed"] is False
    # Looked up by the session save, then read from the table cache by the run save
    assert fresh_db._get_cached_table("aggregate_metrics", fresh_db.aggregate_metrics_table_name) is not None


@pytest.mark.asyncio
async def test_calculate_metrics_dates_releases_the_lock_when_cancelled(
    async_postgres_db_real: AsyncPostgresDb, monkeypatch
):
    """Ensure a calculation cancelled mid-build, as on shutdown, releases the metrics refresh instead of holding it"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(async_postgres_db_real, "_calculate_date_metrics", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await async_postgres_db_real.calculate_metrics_dates()

    refresh_status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)


@pytest.mark.asyncio
async def test_calculate_metrics_counts_tool_calls(async_postgres_db_real: AsyncPostgresDb):
    """Ensure each tool call is counted under its tool from the stored run, including a nested member run's, without
    reading its arguments or result, that a tool call a forked run copied, the user rejected or still waits on is not,
    and that a read adds the tools up"""
    base_time = _noon_utc(2)
    member_run = RunOutput(
        run_id="member_run",
        agent_id="agent-1",
        user_id="bob",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(10, 0),
        messages=[],
        tools=[
            ToolExecution(
                tool_name="search",
                tool_args={"query": "agno"},
                result="x" * 10000,
                metrics=ToolCallMetrics(duration=0.2),
            ),
            ToolExecution(tool_name="search", tool_call_error=True, metrics=ToolCallMetrics(duration=1.2)),
        ],
        created_at=base_time,
    )
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
                model="gpt-5",
                model_provider="OpenAI",
                metrics=_run_metrics(5, 0),
                tools=[ToolExecution(tool_name="delegate_task_to_member", metrics=ToolCallMetrics(duration=1.5))],
                member_responses=[member_run],
                created_at=base_time,
            )
        ],
        created_at=base_time,
        updated_at=base_time,
    )
    await _persist(async_postgres_db_real, team_session)
    fork_session = _session_on(_utc_date(2), "fork_session", "bob")
    original = fork_session.runs[0]
    original.messages = [Message(role="tool", tool_call_id="copied_call", content="agno")]
    original.tools = [
        ToolExecution(tool_call_id="copied_call", tool_name="search", metrics=ToolCallMetrics(duration=0.4)),
        ToolExecution(tool_name="delete_file", tool_call_error=True, requires_confirmation=False, confirmed=False),
        ToolExecution(tool_name="send_email", requires_confirmation=True),
    ]
    forked = RunOutput(
        run_id="forked_run",
        agent_id="agent-1",
        user_id="bob",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(10, 0),
        messages=[
            Message(role="tool", tool_call_id="copied_call", content="agno"),
            Message(role="tool", tool_call_id="new_call", content="agno"),
        ],
        tools=[
            ToolExecution(tool_call_id="copied_call", tool_name="search", metrics=ToolCallMetrics(duration=0.4)),
            ToolExecution(tool_call_id="new_call", tool_name="search", metrics=ToolCallMetrics(duration=0.1)),
        ],
        forked_from_run_id=original.run_id,
        forked_from_message_index=1,
        created_at=original.created_at,
    )
    fork_session.runs.append(forked)
    await _persist(async_postgres_db_real, fork_session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    expected = {
        "": {
            "delegate_task_to_member": {
                "count": 1,
                "failed_count": 0,
                "total_ms": 1500,
                "max_ms": 1500,
                "buckets": {"le_1500": 1},
            },
            "search": {
                "count": 2,
                "failed_count": 1,
                "total_ms": 1400,
                "max_ms": 1200,
                "buckets": {"le_200": 1, "le_1200": 1},
            },
        }
    }
    # The member run is kept only inside its team run, so its tool calls count on the team's row
    assert (await _stored_rows(async_postgres_db_real))[(past_day, "bob", "team", "team-1")]["tool_metrics"] == expected
    # The forked run counts only the tool call it made, and neither the rejected nor the paused call counts
    assert (await _stored_rows(async_postgres_db_real))[(past_day, "bob", "agent", "agent-1")]["tool_metrics"] == {
        "": {
            "search": {
                "count": 2,
                "failed_count": 0,
                "total_ms": 500,
                "max_ms": 400,
                "buckets": {"le_100": 1, "le_400": 1},
            }
        }
    }
    expected[""]["search"] = {
        "count": 4,
        "failed_count": 1,
        "total_ms": 1900,
        "max_ms": 1200,
        "buckets": {"le_100": 1, "le_200": 1, "le_400": 1, "le_1200": 1},
    }
    assert (await _stored_aggregate_metrics_rows(async_postgres_db_real))[("daily", past_day)]["tool_metrics"] == expected

    for user_id in [None, "bob"]:
        metrics, _ = await async_postgres_db_real.get_component_metrics(
            starting_date=past_day, ending_date=past_day, user_id=user_id, fields=["tool_metrics"]
        )
        assert metrics[0]["tool_metrics"] == expected
