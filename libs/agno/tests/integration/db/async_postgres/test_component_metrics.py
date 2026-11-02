"""Integration tests for the component metrics related methods of the AsyncPostgresDb class"""

import asyncio
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text

from agno.db.base import SessionType
from agno.db.postgres import AsyncPostgresDb
from agno.db.postgres.schemas import (
    COMPONENT_METRICS_TABLE_SCHEMA,
    METRICS_REFRESHES_TABLE_SCHEMA,
    USER_METRICS_TABLE_SCHEMA,
)
from agno.db.postgres.utils import areopen_metrics_day, aupsert_user_metrics_row, build_component_metrics_runs_query
from agno.db.utils import (
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_DETAILS_FIELDS,
    METRICS_TOKEN_FIELDS,
    USER_METRICS_COUNT_COLUMNS,
    calculate_date_component_metrics,
    list_metrics_totals_models,
    merge_metrics_totals,
    resolve_metrics_fields,
)
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup_component_metrics_sessions_and_runs(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up component metrics, session and run rows after each test"""
    yield

    for table_type in ["component_metrics", "user_metrics", "metrics_refreshes", "metrics", "runs", "sessions"]:
        try:
            table = await async_postgres_db_real._get_table(table_type, create_table_if_not_found=True)
            async with async_postgres_db_real.async_session_factory() as session:
                await session.execute(table.delete())
                await session.commit()
        except Exception:
            pass  # Ignore cleanup errors for this table


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
        result = await sess.execute(select(table))
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in result.fetchall()
        }


async def _stored_user_metrics_rows(db: AsyncPostgresDb) -> Dict[tuple, Dict]:
    """Every day and month everyone row of agno_user_metrics, keyed by (aggregation_period, date).

    The user rows are left out.
    """
    table = await db._get_table("user_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table).where(table.c.user_id == ""))
        return {(row.aggregation_period, row.date): dict(row._mapping) for row in result.fetchall()}


def _user_metrics_sessions_count(row: Dict) -> int:
    """The sessions of every type a row of agno_user_metrics keeps."""
    return row["agent_sessions_count"] + row["team_sessions_count"] + row["workflow_sessions_count"]


def _merged_totals(rows: List[Dict], fields: List[str]) -> Dict:
    """The totals a read returns for the given rows of agno_component_metrics: the root runs are those no other run
    started."""
    return {
        **list_metrics_totals_models(merge_metrics_totals(rows, fields)),
        "root_runs_count": sum(row["runs_count"] for row in rows if not row["parent_component_id"]),
    }


def _models_by_provider(models: List[Dict]) -> Dict[str, Dict[str, int]]:
    """The models a read lists, counted per provider and model as a row of agno_component_metrics keeps them."""
    by_provider: Dict[str, Dict[str, int]] = {}
    for model in models:
        by_provider.setdefault(model["model_provider"], {})[model["model_id"]] = model["count"]
    return by_provider


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


async def _sessions_counts(db: AsyncPostgresDb, day: date, user_id: Optional[str]) -> List[int]:
    """The sessions_count of each day get_component_metrics returns for the given day, for every owner or one."""
    metrics, _ = await db.get_component_metrics(
        starting_date=day, ending_date=day, user_id=user_id, fields=["sessions_count"]
    )
    return [day_totals["sessions_count"] for day_totals in metrics]


async def _total_sessions_count(
    db: AsyncPostgresDb, starting_date: date, ending_date: date, user_id: Optional[str] = None
) -> int:
    """The sessions_count get_metrics_totals returns for the date range, for every owner or one."""
    totals, _ = await db.get_metrics_totals(
        starting_date=starting_date, ending_date=ending_date, user_id=user_id, fields=["sessions_count"]
    )
    return totals["sessions_count"]


async def _day_versions(db: AsyncPostgresDb, starting_date: date, ending_date: date) -> Dict[str, int]:
    """The version of each day's everyone row of agno_user_metrics in the date range."""
    table = await db._get_table("user_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(
            select(table.c.date, table.c.version).where(
                table.c.aggregation_period == "daily",
                table.c.user_id == "",
                table.c.date >= starting_date,
                table.c.date <= ending_date,
            )
        )
    return {f"daily {row.date.isoformat()}": row.version for row in result.fetchall()}


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
    user_metrics_table = await async_postgres_db_real._get_table("user_metrics", create_table_if_not_found=True)
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)

    assert component_metrics_table.name == async_postgres_db_real.component_metrics_table_name
    assert user_metrics_table.name == async_postgres_db_real.user_metrics_table_name
    assert refreshes_table.name == async_postgres_db_real.metrics_refreshes_table_name
    assert component_metrics_table.schema == user_metrics_table.schema == async_postgres_db_real.db_schema

    assert [col.name for col in component_metrics_table.columns] == [
        column for column in COMPONENT_METRICS_TABLE_SCHEMA if not column.startswith("_")
    ]
    assert {col.name for col in user_metrics_table.columns} == set(USER_METRICS_TABLE_SCHEMA)
    assert [col.name for col in refreshes_table.columns] == list(METRICS_REFRESHES_TABLE_SCHEMA)
    assert set(METRICS_TOKEN_FIELDS) - {*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens"} | {"token_details"} | set(
        USER_METRICS_COUNT_COLUMNS
    ) <= set(USER_METRICS_TABLE_SCHEMA)
    assert "sessions_count" not in USER_METRICS_TABLE_SCHEMA

    async with async_postgres_db_real.db_engine.connect() as conn:
        component_metrics_pk, totals_pk, refreshes_pk, index_list = await conn.run_sync(
            lambda sync_conn: (
                inspect(sync_conn).get_pk_constraint(
                    component_metrics_table.name, schema=component_metrics_table.schema
                ),
                inspect(sync_conn).get_pk_constraint(user_metrics_table.name, schema=user_metrics_table.schema),
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
async def test_calculate_metrics_no_sessions(async_postgres_db_real: AsyncPostgresDb):
    """Ensure calculate_metrics returns no day when there are no sessions"""
    result = await async_postgres_db_real.calculate_metrics()

    assert result == []


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
    assert await _stored_user_metrics_rows(async_postgres_db_real) == {}

    # The other process stopped and released it, so the same call calculates
    await async_postgres_db_real._release_metrics_refresh(refreshes_table, "other_process", error=METRICS_STOPPED_ERROR)
    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    assert len(await _stored_rows(async_postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


@pytest.mark.asyncio
async def test_calculate_metrics_skips_messages_carried_over_from_history(async_postgres_db_real: AsyncPostgresDb):
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
    await _persist(async_postgres_db_real, session)

    await async_postgres_db_real.calculate_metrics()

    row = (await _stored_rows(async_postgres_db_real))[(_utc_date(2), "alice", "agent", "agent-1")]
    assert row["model_calls_count"] == 1
    assert row["total_model_call_ms"] == 1200
    assert row["model_call_buckets"] == {"le_1200": 1}


@pytest.mark.asyncio
async def test_calculate_metrics_skips_messages_a_forked_run_copied(async_postgres_db_real: AsyncPostgresDb):
    """Ensure the messages a forked run copied from the run it was forked from are not counted again"""
    session = _session_on(_utc_date(2), "fork_session", "alice")
    original = session.runs[0]
    forked = RunOutput(
        run_id="forked_run",
        agent_id="agent-1",
        user_id="alice",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(20, 5, duration=2.0),
        messages=[_assistant_message(1.5), _assistant_message(0.5)],
        forked_from_run_id=original.run_id,
        forked_from_message_index=1,
        created_at=original.created_at,
    )
    session.runs.append(forked)
    await _persist(async_postgres_db_real, session)

    await async_postgres_db_real.calculate_metrics()

    row = (await _stored_rows(async_postgres_db_real))[(_utc_date(2), "alice", "agent", "agent-1")]
    assert (row["runs_count"], row["total_tokens"]) == (2, 40)
    assert (row["model_calls_count"], row["total_model_call_ms"]) == (2, 2000)


@pytest.mark.asyncio
async def test_calculate_metrics_skips_runs_a_forked_session_copied(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a run copied into a forked session is not counted again, while the forked session is"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(2), "fork_session", "alice"))
    copied_session = _session_on(_utc_date(2), "copied_session", "alice")
    copied_session.runs[0].forked_from_session_id = "fork_session"
    await _persist(async_postgres_db_real, copied_session)

    await async_postgres_db_real.calculate_metrics()

    row = (await _stored_rows(async_postgres_db_real))[(_utc_date(2), "alice", "agent", "agent-1")]
    assert (row["sessions_count"], row["runs_count"], row["total_tokens"]) == (2, 1, 15)


@pytest.mark.asyncio
async def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a run not yet migrated out of the sessions table's legacy runs column is counted once, on its session's
    day"""
    session = _session_on(_utc_date(2), "legacy_session", "alice")
    session.runs.append(
        RunOutput(
            run_id="legacy_only_run",
            agent_id="agent-1",
            status=RunStatus.completed,
            model="gpt-5",
            model_provider="OpenAI",
            metrics=_run_metrics(30, 5),
            messages=[_assistant_message(0.5)],
            created_at=_noon_utc(2),
        )
    )
    # The first run is in the runs table and the legacy column, the second in the legacy column only
    schema_version = await async_postgres_db_real.get_latest_schema_version(async_postgres_db_real.session_table_name)
    await async_postgres_db_real.upsert_session(session)
    await async_postgres_db_real.upsert_run(
        session.runs[0], session_id=session.session_id, user_id="alice", run_index=0
    )
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN runs JSONB"))
        await sess.execute(
            text("UPDATE test_schema.test_sessions SET runs = CAST(:runs AS JSONB)"),
            {"runs": json.dumps([run.to_dict() for run in session.runs])},
        )
    # The legacy column is read only before the v3.0.0 migration is stamped
    await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, "2.5.0")
    try:
        # A new instance, so the sessions table is read with its legacy column
        legacy_db = AsyncPostgresDb(
            db_engine=async_postgres_db_real.db_engine, db_schema="test_schema", session_table="test_sessions"
        )
        await legacy_db.calculate_metrics()

        row = (await _stored_rows(legacy_db))[(_utc_date(2), "alice", "agent", "agent-1")]
        assert (row["sessions_count"], row["runs_count"], row["total_tokens"]) == (1, 2, 50)
        assert (row["model_calls_count"], row["total_model_call_ms"]) == (2, 2000)
    finally:
        await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, schema_version)
        async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
            await sess.execute(text("ALTER TABLE test_schema.test_sessions DROP COLUMN runs"))


@pytest.mark.asyncio
async def test_a_legacy_run_is_counted_on_its_own_day(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a first calculation builds the day of a run kept only in the legacy runs column, a day with no session"""
    session = AgentSession(session_id="legacy_session", agent_id="agent-1", user_id="alice", created_at=_noon_utc(6))
    legacy_run = RunOutput(
        run_id="legacy_only_run",
        agent_id="agent-1",
        user_id="alice",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(30, 5),
        messages=[],
        created_at=_noon_utc(4),
    )
    schema_version = await async_postgres_db_real.get_latest_schema_version(async_postgres_db_real.session_table_name)
    await async_postgres_db_real.upsert_session(session)
    await async_postgres_db_real._get_table("runs", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN runs JSONB"))
        await sess.execute(
            text("UPDATE test_schema.test_sessions SET runs = CAST(:runs AS JSONB)"),
            {"runs": json.dumps([legacy_run.to_dict()])},
        )
    # The legacy column is read only before the v3.0.0 migration is stamped
    await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, "2.5.0")
    try:
        # A new instance, so the sessions table is read with its legacy column
        legacy_db = AsyncPostgresDb(
            db_engine=async_postgres_db_real.db_engine, db_schema="test_schema", session_table="test_sessions"
        )
        await legacy_db.calculate_metrics()

        assert (await _stored_user_metrics_rows(legacy_db))[("daily", _utc_date(4))]["agent_runs_count"] == 1
    finally:
        await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, schema_version)
        async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
            await sess.execute(text("ALTER TABLE test_schema.test_sessions DROP COLUMN runs"))


@pytest.mark.asyncio
async def test_a_legacy_member_run_kept_as_its_own_run_is_counted_once(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a member run nested inside its team's legacy run, and kept as a legacy run of its own on a later day, is
    counted once, on its own day"""
    session = TeamSession(session_id="legacy_team_session", team_id="team-1", created_at=_noon_utc(6))
    member_run = {
        "run_id": "member_run",
        "agent_id": "member-agent",
        "model": "gpt-5",
        "model_provider": "OpenAI",
        "metrics": {"input_tokens": 10, "output_tokens": 0, "total_tokens": 10},
        "status": "COMPLETED",
    }
    team_run = {
        "run_id": "team_run",
        "team_id": "team-1",
        "model": "gpt-5",
        "model_provider": "OpenAI",
        "metrics": {"input_tokens": 100, "output_tokens": 0, "total_tokens": 100},
        "status": "COMPLETED",
        "created_at": _noon_utc(6),
        "member_responses": [member_run],
    }
    # The member run is also kept as a run of its own, a later day
    legacy_runs = [team_run, {**member_run, "parent_run_id": "team_run", "created_at": _noon_utc(4)}]
    schema_version = await async_postgres_db_real.get_latest_schema_version(async_postgres_db_real.session_table_name)
    await async_postgres_db_real.upsert_session(session)
    await async_postgres_db_real._get_table("runs", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN runs JSONB"))
        await sess.execute(
            text("UPDATE test_schema.test_sessions SET runs = CAST(:runs AS JSONB)"), {"runs": json.dumps(legacy_runs)}
        )
    # The legacy column is read only before the v3.0.0 migration is stamped
    await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, "2.5.0")
    try:
        # A new instance, so the sessions table is read with its legacy column
        legacy_db = AsyncPostgresDb(
            db_engine=async_postgres_db_real.db_engine, db_schema="test_schema", session_table="test_sessions"
        )
        await legacy_db.calculate_metrics()

        user_metrics_rows = await _stored_user_metrics_rows(legacy_db)
        assert user_metrics_rows[("daily", _utc_date(6))]["total_tokens"] == 100
        assert user_metrics_rows[("daily", _utc_date(4))]["total_tokens"] == 10
    finally:
        await async_postgres_db_real.upsert_schema_version(async_postgres_db_real.session_table_name, schema_version)
        async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
            await sess.execute(text("ALTER TABLE test_schema.test_sessions DROP COLUMN runs"))


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
    assert alice_row["model_metrics"] == {"OpenAI": {"gpt-5": 2}}
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
async def test_calculate_metrics_writes_a_total_row_for_each_calculated_day(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure each calculated day gets one user metrics row for every owner, yesterday without traffic included"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    yesterday = _utc_date(1)
    today = _utc_date(0)
    user_metrics_rows = await _stored_user_metrics_rows(async_postgres_db_real)
    assert {key for key in user_metrics_rows if key[0] == "daily"} == {
        ("daily", past_day),
        ("daily", yesterday),
        ("daily", today),
    }

    day_row = user_metrics_rows[("daily", past_day)]
    assert _user_metrics_sessions_count(day_row) == 4
    assert day_row["root_runs_count"] == 5
    assert day_row["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert (day_row["input_tokens"], day_row["output_tokens"], day_row["total_tokens"]) == (385, 185, 570)
    assert day_row["duration_runs_count"] == 4
    assert day_row["max_duration_ms"] == 4000
    assert day_row["duration_buckets"] == {"le_1000": 1, "le_2000": 1, "le_3000": 1, "le_4000": 1}
    assert day_row["model_metrics"] == {"OpenAI": {"gpt-5": 6}}
    assert day_row["completed"] is True
    assert day_row["version"] == 1

    # Yesterday has no traffic and is still open; today is open too
    yesterday_row = user_metrics_rows[("daily", yesterday)]
    assert (
        _user_metrics_sessions_count(yesterday_row),
        yesterday_row["root_runs_count"],
        yesterday_row["max_duration_ms"],
    ) == (
        0,
        0,
        None,
    )
    assert yesterday_row["completed"] is False
    assert _user_metrics_sessions_count(user_metrics_rows[("daily", today)]) == 1
    assert user_metrics_rows[("daily", today)]["completed"] is False


@pytest.mark.asyncio
async def test_calculate_metrics_rewrites_only_changed_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a rebuild leaves unchanged rows alone, rewrites a changed row and drops a stale one"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)

    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    row_count = len(await _stored_rows(async_postgres_db_real))

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    table = await async_postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.update().values(updated_at=1))

    # A session touched without a change: the past day is complete so only yesterday and today are rebuilt, and no
    # row is written
    sessions_table = await async_postgres_db_real._get_table("sessions")
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(sessions_table.update().values(updated_at=int(time.time()) - 60))
    today = _utc_date(0)
    alice_today_row_id = (today, "alice", "agent", "agent-1")
    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    assert [(row["date"], row["user_id"]) for row in result] == [(today, "alice")]
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert len(stored_rows) == row_count
    assert all(row["updated_at"] == 1 for row in stored_rows.values())

    # One more run for alice's session today: only that row is rewritten
    alice_today_session = sample_sessions_for_component_metrics[4]
    await async_postgres_db_real.upsert_run(
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
    await async_postgres_db_real.calculate_metrics()
    stored_rows = await _stored_rows(async_postgres_db_real)
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
    await _persist(async_postgres_db_real, bob_today_session)
    await async_postgres_db_real.calculate_metrics()
    bob_today_row_id = (today, "bob", "agent", "agent-1")
    assert bob_today_row_id in await _stored_rows(async_postgres_db_real)

    assert await async_postgres_db_real.delete_session("bob_today_session") is True
    await async_postgres_db_real.calculate_metrics()
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert len(stored_rows) == row_count
    assert bob_today_row_id not in stored_rows


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
    assert past_day_totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 6}]
    assert metrics[1]["sessions_count"] == 0
    assert metrics[1]["max_duration_ms"] is None
    assert metrics[2]["sessions_count"] == 1
    assert metrics[2]["root_runs_count"] == 1

    # The latest updated_at of the window is the one returned
    user_metrics_rows = await _stored_user_metrics_rows(async_postgres_db_real)
    assert latest_updated_at == max(
        row["updated_at"]
        for (period, row_date), row in user_metrics_rows.items()
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


@pytest.mark.asyncio
async def test_get_component_metrics_fields(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure get_component_metrics returns only the fields asked for"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)

    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=past_day, fields=["total_duration_ms", "max_duration_ms"]
    )
    assert metrics == [{"date": past_day, "total_duration_ms": 10000, "max_duration_ms": 4000}]

    metrics, _ = await async_postgres_db_real.get_component_metrics(
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

    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=past_day, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [{"date": past_day, "sessions_count": 4, "root_runs_count": 5}]

    with pytest.raises(ValueError):
        await async_postgres_db_real.get_component_metrics(
            starting_date=past_day, ending_date=past_day, fields=["users_count"]
        )


@pytest.mark.asyncio
async def test_get_component_metrics_never_calculates_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure get_component_metrics reads only the rows calculate_metrics built"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)

    past_day = _utc_date(2)
    today = _utc_date(0)
    assert await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    ) == ([], None)
    assert await _stored_rows(async_postgres_db_real) == {}

    await async_postgres_db_real.calculate_metrics()
    metrics, latest_updated_at = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    )

    assert latest_updated_at is not None
    assert metrics == [
        {"date": past_day, "sessions_count": 4},
        {"date": _utc_date(1), "sessions_count": 0},
        {"date": today, "sessions_count": 1},
    ]
    assert len(await _stored_rows(async_postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


@pytest.mark.asyncio
async def test_get_component_metrics_no_rows(async_postgres_db_real: AsyncPostgresDb):
    """Ensure get_component_metrics returns nothing when there are no sessions"""
    metrics, latest_updated_at = await async_postgres_db_real.get_component_metrics(
        starting_date=_utc_date(2), ending_date=_utc_date(0)
    )

    assert metrics == []
    assert latest_updated_at is None


@pytest.fixture
def sample_multi_day_sessions_for_component_metrics() -> List[AgentSession]:
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


@pytest.mark.asyncio
async def test_component_metrics_multiple_days(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_day_sessions_for_component_metrics
):
    """Ensure sessions on two days produce rows on both, and a one-day window returns only that day"""
    for session in sample_multi_day_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)

    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    # Each day's row
    assert len(result) == 2

    first_day = _utc_date(3)
    second_day = _utc_date(2)
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert {row["date"] for row in stored_rows.values()} == {first_day, second_day}

    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=first_day, ending_date=second_day, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [
        {"date": first_day, "sessions_count": 2, "root_runs_count": 2},
        {"date": second_day, "sessions_count": 1, "root_runs_count": 1},
    ]

    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=second_day, ending_date=second_day, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [{"date": second_day, "sessions_count": 1, "root_runs_count": 1}]


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
async def test_get_component_metrics_reads_every_owner_from_the_total_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a read equals the sum of the rows, with every owner read from the everyone rows and one owner from its"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    today = _utc_date(0)
    days = [past_day, _utc_date(1), today]
    stored_rows = list((await _stored_rows(async_postgres_db_real)).values())
    fields = resolve_metrics_fields(None)

    # Every owner, then one owner: the same totals as the rows add up to
    metrics, _ = await async_postgres_db_real.get_component_metrics(starting_date=past_day, ending_date=today)
    assert metrics == [
        {"date": day, **_merged_totals([row for row in stored_rows if row["date"] == day], fields)} for day in days
    ]
    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, user_id="bob"
    )
    assert metrics == [
        {"date": past_day, **_merged_totals([row for row in stored_rows if row["user_id"] == "bob"], fields)}
    ]

    # Change every component row: every owner and one owner are still read from the user metrics rows
    table = await async_postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.update().values(sessions_count=50))
    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    )
    assert [day_totals["sessions_count"] for day_totals in metrics] == [4, 0, 1]
    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, user_id="bob", fields=["sessions_count"]
    )
    assert metrics == [
        {
            "date": past_day,
            "sessions_count": sum(row["sessions_count"] for row in stored_rows if row["user_id"] == "bob"),
        }
    ]


@pytest.mark.asyncio
async def test_get_component_metrics_never_reads_a_total_row_for_one_owner(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure one owner's read uses that owner's user metrics row, and the runs with no user their component rows"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    user_metrics_table = await async_postgres_db_real._get_table("user_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            user_metrics_table.update()
            .where(user_metrics_table.c.date == past_day, user_metrics_table.c.user_id == "")
            .values(agent_sessions_count=1000, team_sessions_count=0, workflow_sessions_count=0)
        )

    assert await _sessions_counts(async_postgres_db_real, past_day, None) == [1000]
    assert await _sessions_counts(async_postgres_db_real, past_day, "alice") == [1]
    assert await _sessions_counts(async_postgres_db_real, past_day, "bob") == [2]
    assert await _sessions_counts(async_postgres_db_real, past_day, "") == [1]
    assert await _sessions_counts(async_postgres_db_real, past_day, "carol") == []


@pytest.mark.asyncio
async def test_calculate_metrics_writes_a_month_total_row_for_a_completed_month(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure every month of a calculated day gets a user metrics row, completed once its last day is"""
    for session in sample_multi_month_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    this_month = _month_start(0)
    # The month of yesterday gets its user metrics row even without traffic
    month_totals_rows = {
        key[1]: row
        for key, row in (await _stored_user_metrics_rows(async_postgres_db_real)).items()
        if key[0] == "monthly"
    }
    assert set(month_totals_rows) == {first_month, second_month, _utc_date(1).replace(day=1), this_month}
    assert {month_start for month_start, row in month_totals_rows.items() if row["completed"]} == {
        first_month,
        second_month,
    }

    month_row = month_totals_rows[first_month]
    assert _user_metrics_sessions_count(month_row) == 4
    assert month_row["root_runs_count"] == 4
    assert (month_row["input_tokens"], month_row["output_tokens"], month_row["total_tokens"]) == (165, 20, 185)
    assert month_row["duration_buckets"] == {"le_2000": 4}
    assert month_row["completed"] is True
    alice_totals, _ = await async_postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), user_id="alice"
    )
    assert alice_totals["sessions_count"] == 2
    assert alice_totals["input_tokens"] == 120
    assert alice_totals["model_metrics"] == [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}]
    # The runs with no user are read from their day rows
    unowned_totals, _ = await async_postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), user_id=""
    )
    assert unowned_totals["sessions_count"] == 1
    assert _user_metrics_sessions_count(month_totals_rows[second_month]) == 1


@pytest.mark.asyncio
async def test_calculate_metrics_rebuilds_the_month_of_a_reopened_day(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure a month without a month user metrics row gets it back once a write reopens one of its days"""
    for session in sample_multi_month_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    user_metrics_table = await async_postgres_db_real._get_table("user_metrics", create_table_if_not_found=True)

    # The first month loses its month user metrics rows
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            user_metrics_table.delete().where(
                user_metrics_table.c.aggregation_period == "monthly", user_metrics_table.c.date == first_month
            )
        )

    # A new session of carol reopens the 15th
    await _persist(async_postgres_db_real, _session_on(first_month + timedelta(days=14), "first_month_carol", "carol"))
    result = await async_postgres_db_real.calculate_metrics()
    assert result is not None
    assert (first_month + timedelta(days=14), "carol") in {(row["date"], row["user_id"]) for row in result}
    assert (
        _user_metrics_sessions_count(
            (await _stored_user_metrics_rows(async_postgres_db_real))[("monthly", first_month)]
        )
        == 5
    )


@pytest.mark.asyncio
async def test_get_metrics_totals(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure the totals of a date range equal its days' totals summed, for every owner or one"""
    for session in sample_multi_month_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    today = _utc_date(0)
    fields = resolve_metrics_fields(None)
    windows = [
        # A whole month, part of a month, and both months with every day since
        (first_month, second_month - timedelta(days=1)),
        (first_month + timedelta(days=9), second_month + timedelta(days=9)),
        (first_month, today),
    ]
    for starting_date, ending_date in windows:
        for user_id in (None, "alice", "bob", "", "carol"):
            totals, _ = await async_postgres_db_real.get_metrics_totals(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            metrics, _ = await async_postgres_db_real.get_component_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            by_provider = [{**day, "model_metrics": _models_by_provider(day["model_metrics"])} for day in metrics]
            assert totals == list_metrics_totals_models(merge_metrics_totals(by_provider, fields))

    totals, _ = await async_postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=today, fields=["sessions_count", "root_runs_count"]
    )
    assert totals == {"sessions_count": 6, "root_runs_count": 6}
    totals, latest_updated_at = await async_postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=today, user_id="carol", fields=["sessions_count", "model_metrics"]
    )
    assert totals == {"sessions_count": 0, "model_metrics": []}
    assert latest_updated_at is None


@pytest.mark.asyncio
async def test_get_metrics_totals_reads_a_whole_month_from_its_month_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure a month inside the date range is read from its month rows, each owner from their own user metrics row"""
    for session in sample_multi_month_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    user_metrics_table = await async_postgres_db_real._get_table("user_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            user_metrics_table.update()
            .where(
                user_metrics_table.c.aggregation_period == "monthly",
                user_metrics_table.c.date == first_month,
                user_metrics_table.c.user_id == "",
            )
            .values(agent_sessions_count=1000, team_sessions_count=0, workflow_sessions_count=0)
        )
        await sess.execute(
            user_metrics_table.update()
            .where(
                user_metrics_table.c.aggregation_period == "monthly",
                user_metrics_table.c.date == first_month,
                user_metrics_table.c.user_id == "bob",
            )
            .values(agent_sessions_count=500, team_sessions_count=0, workflow_sessions_count=0)
        )

    # The whole first month comes from its month row, with the days after it added
    assert await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1)) == 1000
    assert await _total_sessions_count(async_postgres_db_real, first_month, _utc_date(0)) == 1002
    # A month partly outside the date range is read from its days
    assert (
        await _total_sessions_count(
            async_postgres_db_real, first_month + timedelta(days=1), second_month - timedelta(days=1)
        )
        == 2
    )
    assert await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=2)) == 4
    # One owner's month comes from that owner's month rows
    assert (
        await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1), "alice") == 2
    )
    assert (
        await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1), "bob") == 500
    )
    assert await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1), "") == 1
    # The read of each day never uses a month row, and a day without traffic has no user metrics row to read
    metrics, _ = await async_postgres_db_real.get_component_metrics(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), fields=["sessions_count"]
    )
    assert metrics == [
        {"date": first_month, "sessions_count": 2},
        {"date": first_month + timedelta(days=14), "sessions_count": 2},
    ]


@pytest.mark.asyncio
async def test_calculate_metrics_counts_a_run_of_the_same_second(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a run stored right after a calculation is counted by the next one and moves its day's version"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)

    assert await async_postgres_db_real.calculate_metrics() is not None
    versions = await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0))
    today_key = f"daily {_utc_date(0).isoformat()}"

    # One more run today: counted even when it lands in the same second as the calculation before it
    alice_today_session = sample_sessions_for_component_metrics[4]
    await async_postgres_db_real.upsert_run(
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
    assert await async_postgres_db_real.calculate_metrics() is not None
    assert (await _stored_rows(async_postgres_db_real))[(_utc_date(0), "alice", "agent", "agent-1")]["runs_count"] == 2
    assert await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0)) == {
        **versions,
        today_key: versions[today_key] + 1,
    }


@pytest.mark.asyncio
async def test_calculate_metrics_with_nothing_new_leaves_every_version(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a rebuild that writes nothing moves no version"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    versions = await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0))
    assert await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0)) == {
        f"daily {_utc_date(days_ago).isoformat()}": 1 for days_ago in (2, 1, 0)
    }

    await async_postgres_db_real.calculate_metrics()
    assert await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0)) == versions


@pytest.mark.asyncio
async def test_metrics_versions_move_only_for_the_day_that_changed(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a rebuild that writes or deletes a day's rows moves that day's version and no other"""
    for session in sample_sessions_for_component_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()
    versions = await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0))
    today_key = f"daily {_utc_date(0).isoformat()}"

    # The only session of today is gone: its row is deleted and none is written, and today's version still moves
    assert await async_postgres_db_real.delete_session(sample_sessions_for_component_metrics[4].session_id) is True
    await async_postgres_db_real.calculate_metrics()
    assert await _day_versions(async_postgres_db_real, _utc_date(2), _utc_date(0)) == {
        **versions,
        today_key: versions[today_key] + 1,
    }
    # Only the user metrics rows inside the date range are returned
    assert await _day_versions(async_postgres_db_real, _utc_date(1), _utc_date(1)) == {
        f"daily {_utc_date(1).isoformat()}": 1
    }


@pytest.mark.asyncio
async def test_calculate_metrics_counts_a_late_run_of_yesterday(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a run started before midnight and stored after a rebuild of today is counted on yesterday"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    await async_postgres_db_real.calculate_metrics()
    versions = await _day_versions(async_postgres_db_real, _utc_date(1), _utc_date(0))
    yesterday_key = f"daily {_utc_date(1).isoformat()}"
    assert versions[yesterday_key] == 1
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(1))]["root_runs_count"] == 0

    # Started at 23:59 yesterday, stored now
    yesterday = _utc_date(1)
    late_created_at = int(
        datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, tzinfo=timezone.utc).timestamp()
    )
    await _persist(async_postgres_db_real, _session_at(late_created_at, "bob_late", "bob"))
    assert await async_postgres_db_real.calculate_metrics() is not None

    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", yesterday)]["root_runs_count"] == 1
    assert (yesterday, "bob", "agent", "agent-1") in await _stored_rows(async_postgres_db_real)
    assert await _day_versions(async_postgres_db_real, _utc_date(1), _utc_date(0)) == {
        **versions,
        yesterday_key: 2,
    }


@pytest.mark.asyncio
async def test_calculate_metrics_never_rebuilds_an_empty_or_completed_day(
    async_postgres_db_real: AsyncPostgresDb, monkeypatch
):
    """Ensure a first calculation builds only the days with traffic besides yesterday and today, and a later rebuild
    leaves a completed day alone"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_3_days_ago", "alice"))
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    await async_postgres_db_real.calculate_metrics()

    user_metrics_rows = await _stored_user_metrics_rows(async_postgres_db_real)
    assert ("daily", _utc_date(2)) not in user_metrics_rows
    assert user_metrics_rows[("daily", _utc_date(3))]["completed"] is True

    calculated_days = []

    def _calculate(date_to_process, *args):
        calculated_days.append(date_to_process)
        return calculate_date_component_metrics(date_to_process, *args)

    monkeypatch.setattr("agno.db.postgres.async_postgres.calculate_date_component_metrics", _calculate)
    # A new session today moves yesterday and today
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "alice_today_2", "alice"))
    await async_postgres_db_real.calculate_metrics()
    assert calculated_days == [_utc_date(1), _utc_date(0)]


@pytest.mark.asyncio
async def test_calculate_metrics_after_a_delete_moves_the_day(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a rebuild that only deletes a row reports the change, moves the day's everyone row and keeps its totals"""
    alice_today_session = sample_sessions_for_component_metrics[4]
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
    for session in [*sample_sessions_for_component_metrics, bob_today_session]:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        for table_type in ("component_metrics", "user_metrics"):
            table = await async_postgres_db_real._get_table(table_type, create_table_if_not_found=True)
            await sess.execute(table.update().values(updated_at=1))

    assert await async_postgres_db_real.delete_session("bob_today_session") is True
    assert await async_postgres_db_real.calculate_metrics() is not None

    # Bob's row is gone, and today's user metrics row is rewritten, so a read of the day reports the new time
    today = _utc_date(0)
    metrics, read_updated_at = await async_postgres_db_real.get_component_metrics(
        starting_date=today, ending_date=today, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [{"date": today, "sessions_count": 1, "root_runs_count": 1}]
    assert read_updated_at != 1
    user_metrics_rows = await _stored_user_metrics_rows(async_postgres_db_real)
    assert read_updated_at == user_metrics_rows[("daily", today)]["updated_at"]
    assert all(
        row["updated_at"] == 1 for key, row in user_metrics_rows.items() if key[0] == "daily" and key[1] != today
    )


@pytest.mark.asyncio
async def test_calculate_metrics_reads_nested_run_ids_in_chunks(async_postgres_db_real: AsyncPostgresDb, monkeypatch):
    """Ensure a day with more nested runs than one statement is given finds every one stored as a run of its own"""
    monkeypatch.setattr("agno.db.postgres.async_postgres.METRICS_IN_LIST_LIMIT", 2)
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
    await _persist(async_postgres_db_real, team_session)
    await async_postgres_db_real.calculate_metrics()

    # Every member run is stored as a run of its own, so none is counted again from the team run
    past_day = _utc_date(2)
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert stored_rows[(past_day, "bob", "team", "team-1")]["input_tokens"] == 0
    assert stored_rows[(past_day, "bob", "agent", "agent-2")]["runs_count"] == 5
    assert stored_rows[(past_day, "bob", "agent", "agent-2")]["input_tokens"] == 50
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", past_day)]["input_tokens"] == 50


@pytest.mark.asyncio
async def test_calculate_metrics_counts_a_remote_member_run_once(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a remote member's run kept inside its team run and stored as a run of its own by the AgentOS that ran it,
    in the same database, is counted once, from its own row"""
    base_time = _noon_utc(2)
    member_run = RunOutput(
        run_id="remote_member_run",
        agent_id="remote-agent",
        session_id="team_session:remote-agent",
        user_id="bob",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(10, 0),
        messages=[],
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
                member_responses=[member_run],
                created_at=base_time,
            )
        ],
        created_at=base_time,
        updated_at=base_time,
    )
    # The remote AgentOS stores its run in a session of its own
    remote_session = AgentSession(
        session_id="team_session:remote-agent",
        agent_id="remote-agent",
        user_id="bob",
        runs=[member_run],
        created_at=base_time,
        updated_at=base_time,
    )
    await _persist(async_postgres_db_real, team_session)
    await _persist(async_postgres_db_real, remote_session)
    await async_postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert stored_rows[(past_day, "bob", "team", "team-1")]["input_tokens"] == 0
    assert stored_rows[(past_day, "bob", "agent", "remote-agent")]["input_tokens"] == 10
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", past_day)]["input_tokens"] == 10


@pytest.mark.asyncio
async def test_calculate_metrics_names_a_parent_run_of_the_day_before(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a member run started after midnight by a team run of the day before names that team as its parent"""
    midnight = _noon_utc(2) - 12 * 3600
    member_run = RunOutput(
        run_id="member_run",
        agent_id="agent-2",
        user_id="bob",
        parent_run_id="team_run",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(10, 0),
        messages=[],
        created_at=midnight + 60,
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
                created_at=midnight - 60,
            ),
            member_run,
        ],
        created_at=midnight - 60,
        updated_at=midnight + 60,
    )
    await _persist(async_postgres_db_real, team_session)
    await async_postgres_db_real.calculate_metrics()

    rows = await _stored_rows(async_postgres_db_real)
    assert rows[(_utc_date(2), "bob", "agent", "agent-2")]["parent_component_id"] == "team-1"


@pytest.mark.asyncio
async def test_calculate_metrics_stores_each_day_as_it_is_calculated(
    async_postgres_db_real: AsyncPostgresDb, monkeypatch
):
    """Ensure a day that fails to calculate leaves the days before it stored, and the next rebuild writes the rest"""
    for days_ago in [3, 2, 1, 0]:
        await _persist(async_postgres_db_real, _session_on(_utc_date(days_ago), f"alice_{days_ago}_days_ago", "alice"))

    def _fail_two_days_ago(date_to_process, *args):
        if date_to_process == _utc_date(2):
            raise RuntimeError("Two days ago cannot be calculated")
        return calculate_date_component_metrics(date_to_process, *args)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.async_postgres.calculate_date_component_metrics", _fail_two_days_ago)
        with pytest.raises(RuntimeError):
            await async_postgres_db_real.calculate_metrics()
    assert {row_id[0] for row_id in await _stored_rows(async_postgres_db_real)} == {_utc_date(3)}
    # The stored day reopened its month for the next calculation
    assert set(await _stored_user_metrics_rows(async_postgres_db_real)) == {
        ("daily", _utc_date(3)),
        ("monthly", _utc_date(3).replace(day=1)),
    }

    await async_postgres_db_real.calculate_metrics()
    assert {row_id[0] for row_id in await _stored_rows(async_postgres_db_real)} == {
        _utc_date(3),
        _utc_date(2),
        _utc_date(1),
        _utc_date(0),
    }


@pytest.mark.asyncio
async def test_calculate_metrics_counts_nested_runs_at_every_depth(async_postgres_db_real: AsyncPostgresDb):
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
    await _persist(async_postgres_db_real, session)

    runs_table = await async_postgres_db_real._get_table("runs")
    async with async_postgres_db_real.async_session_factory() as sess:
        result = await sess.execute(build_component_metrics_runs_query(runs_table, _noon_utc(2), _noon_utc(2) + 1))
        (run,) = result.fetchall()
    assert [(nested_run["depth"], nested_run["run_id"]) for nested_run in run.nested_runs] == [
        (1, "nested_member"),
        (1, "nested_inner_team"),
        (2, "nested_inner_member"),
    ]
    assert all("messages" not in nested_run for nested_run in run.nested_runs)
    assert [nested_run["call_durations"] for nested_run in run.nested_runs] == [[0.6], [0.5], [0.4]]

    await async_postgres_db_real.calculate_metrics()

    # The nested runs are no runs of their own, so their tokens and calls are on the row of the team run
    row = (await _stored_rows(async_postgres_db_real))[(_utc_date(2), "alice", "team", "team-1")]
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (19, 9, 28)
    assert row["model_calls_count"] == 4
    assert row["total_model_call_ms"] == 2700
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": 4}}


@pytest.mark.asyncio
async def test_calculate_metrics_skips_a_refresh_with_nothing_new(async_postgres_db_real: AsyncPostgresDb):
    """A calculation skips the rebuild while no session or run changed, and rebuilds after one did"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "skipped_session", "alice"))
    # Written a minute ago, so no write shares the current second
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = await async_postgres_db_real._get_table(table_type)
            await sess.execute(table.update().values(updated_at=int(time.time()) - 60))

    assert await async_postgres_db_real.calculate_metrics()
    assert await async_postgres_db_real.calculate_metrics_dates() == []
    # Nothing changed, so calculate_metrics returns today's metrics as they are
    assert [metric["date"] for metric in await async_postgres_db_real.calculate_metrics()] == [_utc_date(0)]

    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "new_session", "alice"))
    assert await async_postgres_db_real.calculate_metrics() is not None
    assert await _sessions_counts(async_postgres_db_real, _utc_date(0), None) == [2]


@pytest.mark.asyncio
async def test_calculate_metrics_rebuilds_a_reopened_day(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a run saved on a completed day reopens it, and the next calculation completes it again"""
    session = _session_on(_utc_date(5), "alice_5_days_ago", "alice")
    await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()
    day_key = ("daily", _utc_date(5))
    day_row = (await _stored_user_metrics_rows(async_postgres_db_real))[day_key]
    assert day_row["completed"] is True

    await async_postgres_db_real.upsert_run(
        RunOutput(
            run_id="alice_late_run",
            agent_id="agent-1",
            user_id="alice",
            status=RunStatus.completed,
            messages=[],
            created_at=session.created_at + 60,
        ),
        session_id=session.session_id,
        user_id=session.user_id,
        run_index=1,
    )
    reopened_row = (await _stored_user_metrics_rows(async_postgres_db_real))[day_key]
    assert (reopened_row["completed"], reopened_row["version"]) == (False, day_row["version"] + 1)

    await async_postgres_db_real.calculate_metrics()
    rebuilt_row = (await _stored_user_metrics_rows(async_postgres_db_real))[day_key]
    assert (rebuilt_row["completed"], rebuilt_row["root_runs_count"]) == (True, 2)


@pytest.mark.asyncio
async def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(
    async_postgres_db_real: AsyncPostgresDb, monkeypatch
):
    """Ensure a day reopened between the read of its version and its everyone row stays open for the next calculation"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(5), "alice_5_days_ago", "alice"))

    async def _reopen_before_the_upsert(session, table, user_metrics_row, read_version):
        if (user_metrics_row["aggregation_period"], user_metrics_row["date"]) == ("daily", _utc_date(5)):
            # Another connection, as a write committed while the day is rebuilt
            async with async_postgres_db_real.db_engine.begin() as other:
                await areopen_metrics_day(session=other, table=table, day=user_metrics_row["date"])
        await aupsert_user_metrics_row(
            session=session, table=table, user_metrics_row=user_metrics_row, read_version=read_version
        )

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.async_postgres.aupsert_user_metrics_row", _reopen_before_the_upsert)
        await async_postgres_db_real.calculate_metrics()
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(5))]["completed"] is False

    await async_postgres_db_real.calculate_metrics()
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(5))]["completed"] is True


@pytest.mark.asyncio
async def test_get_metrics_reads_the_metrics_table_until_the_first_calculation_finished(
    async_postgres_db_real: AsyncPostgresDb, monkeypatch
):
    """Ensure get_metrics of a database AgentOS calculates never calculates, and reads the metrics table until the
    first calculation has finished"""
    async_postgres_db_real.stop_metrics_refresh_on_read()
    await _persist(async_postgres_db_real, _session_on(_utc_date(2), "alice_2_days_ago", "alice"))
    metrics_table = await async_postgres_db_real._get_table("metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            metrics_table.insert().values(
                {
                    "id": "stored_metrics_row",
                    "date": _utc_date(2),
                    "aggregation_period": "daily",
                    "user_id": "alice",
                    **{column: 0 for column in USER_METRICS_COUNT_COLUMNS},
                    "agent_sessions_count": 7,
                    "token_metrics": {},
                    "model_metrics": [],
                    "created_at": int(time.time()),
                    "completed": True,
                }
            )
        )

    async def _calculate():
        raise AssertionError("get_metrics never calculates metrics")

    with monkeypatch.context() as patch:
        patch.setattr(async_postgres_db_real, "calculate_metrics", _calculate)
        metrics, _ = await async_postgres_db_real.get_metrics()
    assert [(row["id"], row["agent_sessions_count"]) for row in metrics] == [("stored_metrics_row", 7)]

    await async_postgres_db_real.calculate_metrics()
    metrics, _ = await async_postgres_db_real.get_metrics()
    assert [(row["date"], row["user_id"], row["agent_sessions_count"]) for row in metrics] == [
        (_utc_date(2), "alice", 1)
    ]


@pytest.mark.asyncio
async def test_upsert_session_without_a_user_metrics_table(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a session and its run of a past day are saved before any user metrics table exists"""
    db = AsyncPostgresDb(
        db_engine=async_postgres_db_real.db_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        user_metrics_table="test_unbuilt_user_metrics",
    )
    await _persist(db, _session_on(_utc_date(5), "alice_5_days_ago", "alice"))

    assert await db.get_session("alice_5_days_ago") is not None
    assert await db.get_run("alice_5_days_ago_run") is not None
    assert await db.table_exists("test_unbuilt_user_metrics") is False


@pytest.mark.asyncio
async def test_calculate_metrics_keeps_an_everyone_row_and_a_row_per_user(async_postgres_db_real: AsyncPostgresDb):
    """Ensure each day has an everyone row with every run, a row per user, and no row for the runs with no user"""
    past_day = _utc_date(2)
    await _persist(async_postgres_db_real, _session_on(past_day, "alice_session", "alice", input_tokens=10))
    await _persist(async_postgres_db_real, _session_on(past_day, "bob_session", "bob", input_tokens=20))
    await _persist(async_postgres_db_real, _session_on(past_day, "unowned_session", None, input_tokens=30))
    await async_postgres_db_real.calculate_metrics()

    user_metrics_table = await async_postgres_db_real._get_table("user_metrics")
    async with async_postgres_db_real.async_session_factory() as sess:
        result = await sess.execute(
            select(user_metrics_table).where(
                user_metrics_table.c.aggregation_period == "daily", user_metrics_table.c.date == past_day
            )
        )
        rows = {row.user_id: row for row in result.fetchall()}
    assert sorted(rows) == ["", "alice", "bob"]
    assert (rows[""].input_tokens, rows[""].users_count) == (60, 2)
    assert (rows["alice"].input_tokens, rows["alice"].users_count) == (10, 1)

    # Every user's rows, plus the runs with no user from their component rows
    metrics, _ = await async_postgres_db_real.get_metrics(starting_date=past_day, ending_date=past_day)
    assert [(metric["user_id"], metric["token_metrics"]["input_tokens"]) for metric in metrics] == [
        (None, 30),
        ("alice", 10),
        ("bob", 20),
    ]
    metrics, _ = await async_postgres_db_real.get_metrics(starting_date=past_day, ending_date=past_day, user_id="")
    assert [(metric["user_id"], metric["token_metrics"]["input_tokens"]) for metric in metrics] == [(None, 30)]
    # Every user in one row per day, read from the everyone row
    metrics, _ = await async_postgres_db_real.get_metrics_by_date(starting_date=past_day, ending_date=past_day)
    assert [(metric["users_count"], metric["token_metrics"]["input_tokens"]) for metric in metrics] == [(2, 60)]
    # One version per day: the everyone row's
    assert list(await _day_versions(async_postgres_db_real, past_day, past_day)) == [f"daily {past_day.isoformat()}"]


@pytest.mark.asyncio
async def test_calculate_metrics_builds_a_day_written_while_it_was_today(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a day written while it was today, with no calculation until it was older, still gets its rows"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "today_session", "alice"))
    await async_postgres_db_real.calculate_metrics()

    # Written as today three days ago, which reopens no day, and calculated for the last time four days ago
    sessions_table = await async_postgres_db_real._get_table("sessions")
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes")
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            sessions_table.insert().values(
                session_id="late_session",
                session_type="agent",
                agent_id="agent-1",
                user_id="alice",
                created_at=_noon_utc(3),
            )
        )
        await sess.execute(refreshes_table.update().values(finished_at=_noon_utc(4)))
    await async_postgres_db_real.calculate_metrics()

    assert (
        _user_metrics_sessions_count((await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))])
        == 1
    )


@pytest.mark.asyncio
async def test_session_save_reopens_the_day_the_session_is_stored_on(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a save that moves a session to another component reopens the day it was created on, not today"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(5), "moved_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(5))]["completed"] is True

    moved = AgentSession(session_id="moved_session", agent_id="agent-2", user_id="alice", created_at=int(time.time()))
    await async_postgres_db_real.upsert_session(moved)

    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(5))]["completed"] is False


@pytest.mark.asyncio
async def test_calculate_metrics_names_the_run_of_the_tool_call_as_parent(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a run started from another run's tool call names that run's agent as its parent and root"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(2), "outer_session", "alice"))
    nested_session = _session_on(_utc_date(2), "nested_session", "alice")
    nested_session.agent_id = "agent-2"
    nested_session.runs[0].agent_id = "agent-2"
    # A run started from a tool call names the run whose tool started it
    nested_run = {**nested_session.runs[0].to_dict(), "called_from_run_id": "outer_session_run"}
    await async_postgres_db_real.upsert_session(nested_session)
    await async_postgres_db_real.upsert_run(nested_run, session_id="nested_session", user_id="alice", run_index=0)

    await async_postgres_db_real.calculate_metrics()

    rows = {
        (key[3], row["parent_component_id"], row["root_component_id"])
        for key, row in (await _stored_rows(async_postgres_db_real)).items()
    }
    assert ("agent-2", "agent-1", "agent-1") in rows


@pytest.mark.asyncio
async def test_calculate_metrics_takes_over_a_lock_that_went_stale(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a metrics refresh whose process stopped before releasing it reads failed once its lock went stale, and
    is taken over"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert await async_postgres_db_real._claim_metrics_refresh(refreshes_table, "stopped_process") is not None
    assert (await async_postgres_db_real.get_metrics_refresh_status())["status"] == "running"
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(refreshes_table.update().values(locked_at=0))

    refresh_status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert await async_postgres_db_real.calculate_metrics()
    assert (await async_postgres_db_real.get_metrics_refresh_status())["status"] == "completed"


@pytest.mark.asyncio
async def test_calculate_metrics_records_a_failed_refresh(async_postgres_db_real: AsyncPostgresDb, monkeypatch):
    """Ensure a calculation that fails leaves its error on the metrics refresh, read as a failed refresh"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))

    def _fail(*args):
        raise RuntimeError("The day cannot be calculated\n[SQL: SELECT run_data FROM test_schema.test_sessions_runs]")

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.async_postgres.calculate_date_component_metrics", _fail)
        with pytest.raises(RuntimeError):
            await async_postgres_db_real.calculate_metrics()

    # Only the first line is kept, never the statement
    status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", "The day cannot be calculated")


@pytest.mark.asyncio
async def test_deleting_a_session_keeps_its_closed_day_closed(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a deleted session's usage stays on its closed day: the delete reopens nothing"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    day_row = (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]

    assert await async_postgres_db_real.delete_session("alice_session") is True

    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))] == day_row


@pytest.mark.asyncio
async def test_a_run_save_never_fails_because_of_metrics(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a run of a closed day is saved when its day cannot be reopened, as with a totals table missing columns"""
    broken_db = AsyncPostgresDb(
        db_engine=async_postgres_db_real.db_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        user_metrics_table="broken_user_metrics",
    )
    session = _session_on(_utc_date(3), "alice_session", "alice")
    try:
        await broken_db._get_table("sessions", create_table_if_not_found=True)
        async with broken_db.async_session_factory() as sess, sess.begin():
            await sess.execute(
                text("CREATE TABLE test_schema.broken_user_metrics (aggregation_period VARCHAR, date DATE)")
            )
        await _persist(broken_db, session)

        assert await broken_db.get_run(session.runs[0].run_id) is not None
    finally:
        async with broken_db.async_session_factory() as sess, sess.begin():
            await sess.execute(text("DROP TABLE IF EXISTS test_schema.broken_user_metrics"))


@pytest.mark.asyncio
async def test_a_day_is_never_written_by_a_process_that_lost_the_lock(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a calculation whose lock went stale writes nothing once another process took the refresh over"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    table = await async_postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    user_metrics_table = await async_postgres_db_real._get_table("user_metrics", create_table_if_not_found=True)
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert await async_postgres_db_real._claim_metrics_refresh(refreshes_table, "paused") is not None

    # The lock goes stale, and another process takes the refresh over
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(refreshes_table.update().values(locked_at=0))
    assert await async_postgres_db_real._claim_metrics_refresh(refreshes_table, "taker") is not None

    calculated = await async_postgres_db_real._calculate_date_metrics(
        table,
        user_metrics_table,
        await async_postgres_db_real._get_table("sessions"),
        await async_postgres_db_real._get_table("runs"),
        _utc_date(3),
        [],
        {},
        refreshes_table,
        "paused",
    )
    assert calculated is False
    assert await _stored_rows(async_postgres_db_real) == {}
    assert await _stored_user_metrics_rows(async_postgres_db_real) == {}


@pytest.mark.asyncio
async def test_a_save_of_a_closed_day_from_a_fresh_process_is_stored(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a save that reopens a closed day is stored by a process that never looked the totals table up"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(5), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    fresh_db = AsyncPostgresDb(
        db_engine=async_postgres_db_real.db_engine, db_schema="test_schema", session_table="test_sessions"
    )

    bob_session = _session_on(_utc_date(5), "bob_session", "bob")
    await _persist(fresh_db, bob_session)

    assert await fresh_db.get_run(bob_session.runs[0].run_id) is not None
    assert len(await fresh_db.get_sessions(session_type=SessionType.AGENT)) == 2
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(5))]["completed"] is False
    # Looked up once, then read from the table cache by every later save
    assert fresh_db._get_cached_table("user_metrics", fresh_db.user_metrics_table_name) is not None


@pytest.mark.asyncio
async def test_cancelling_a_pending_run_reopens_its_day(async_postgres_db_real: AsyncPostgresDb):
    """Ensure cancelling a pending run of a closed day reopens the day, as every other run write does"""
    session = _session_on(_utc_date(3), "alice_session", "alice")
    session.runs[0].status = RunStatus.pending
    await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()

    assert await async_postgres_db_real.cancel_pending_run(
        "alice_session_run", session_id="alice_session", reason="stopped", user_id="alice"
    )
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]["completed"] is False


@pytest.mark.asyncio
async def test_a_day_a_write_could_not_reopen_is_reopened_by_the_next_write(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a day whose reopen failed is reopened by the next write once its user metrics row can be written again"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    table_name = async_postgres_db_real.user_metrics_table_name
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            text(
                "CREATE FUNCTION test_schema.refuse_user_metrics_writes() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'refused'; END $$ LANGUAGE plpgsql"
            )
        )
        await sess.execute(
            text(
                f"CREATE TRIGGER refuse_user_metrics_writes BEFORE INSERT OR UPDATE ON test_schema.{table_name} "
                "FOR EACH ROW EXECUTE FUNCTION test_schema.refuse_user_metrics_writes()"
            )
        )
    try:
        await _persist(async_postgres_db_real, _session_on(_utc_date(3), "bob_session", "bob"))
        assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]["completed"] is True
    finally:
        async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
            await sess.execute(text(f"DROP TRIGGER IF EXISTS refuse_user_metrics_writes ON test_schema.{table_name}"))
            await sess.execute(text("DROP FUNCTION IF EXISTS test_schema.refuse_user_metrics_writes()"))

    # A write of today, which reopens no day of its own
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "carol_session", "carol"))

    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]["completed"] is False


@pytest.mark.asyncio
async def test_a_stopped_calculation_releases_the_lock(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a calculation stopped between days, as on shutdown, releases the metrics refresh instead of holding it"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))

    assert await async_postgres_db_real.calculate_metrics_dates(should_stop=lambda: True) is None

    refresh_status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert await async_postgres_db_real.calculate_metrics() is not None


@pytest.mark.asyncio
async def test_a_calculation_stops_between_the_batches_of_a_day(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a stop asked during a day stops it at its next batch, before the day is written"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    # Checked before the day, then between its batches
    checks = iter([False])

    assert await async_postgres_db_real.calculate_metrics_dates(should_stop=lambda: next(checks, True)) is None

    assert ("daily", _utc_date(3)) not in await _stored_user_metrics_rows(async_postgres_db_real)
    refresh_status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)


@pytest.mark.asyncio
async def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(async_postgres_db_real: AsyncPostgresDb):
    """Ensure rebuild_from recounts a closed day that no write reopened"""
    session = _session_on(_utc_date(3), "alice_session", "alice")
    await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_metrics()
    # A delete reopens no day, so the closed day keeps the run
    await async_postgres_db_real.delete_run(session.runs[0].run_id)
    await async_postgres_db_real.calculate_metrics()
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]["root_runs_count"] == 1

    await async_postgres_db_real.calculate_metrics(rebuild_from=_utc_date(3))

    day_row = (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]
    assert (day_row["root_runs_count"], day_row["completed"]) == (0, True)


@pytest.mark.asyncio
async def test_calculate_metrics_rebuild_from_builds_a_day_no_calculation_built(
    async_postgres_db_real: AsyncPostgresDb,
):
    """Ensure rebuild_from builds a day with a session but no everyone row, as one written without reopening its day"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    await async_postgres_db_real.calculate_metrics()
    sessions_table = await async_postgres_db_real._get_table("sessions")
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            sessions_table.insert().values(
                session_id="unbuilt_session",
                session_type="agent",
                agent_id="agent-1",
                user_id="alice",
                created_at=_noon_utc(15),
            )
        )
    await async_postgres_db_real.calculate_metrics()
    assert ("daily", _utc_date(15)) not in await _stored_user_metrics_rows(async_postgres_db_real)

    await async_postgres_db_real.calculate_metrics(rebuild_from=_utc_date(20))

    assert (
        _user_metrics_sessions_count(
            (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(15))]
        )
        == 1
    )


@pytest.mark.asyncio
async def test_a_calculation_stopped_after_a_completed_one_reads_completed(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a calculation stopped between days after one that completed, as on a deploy, keeps reading the last
    completed refresh, and leaves the days it did not reach open"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    finished_at = (await async_postgres_db_real.get_metrics_refresh_status())["finished_at"]
    # A new session reopens a closed day
    await _persist(async_postgres_db_real, _session_on(_utc_date(4), "bob_session", "bob"))

    assert await async_postgres_db_real.calculate_metrics_dates(should_stop=lambda: True) is None

    refresh_status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["finished_at"], refresh_status["error"]) == (
        "completed",
        finished_at,
        None,
    )
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(4))]["completed"] is False


@pytest.mark.asyncio
async def test_calculate_metrics_rebuilds_a_month_a_stopped_calculation_left(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a calculation that stopped after a day of a past month leaves the month to the next one, which totals it
    from its days"""
    last_month_day = _month_start(0) - timedelta(days=1)
    await _persist(async_postgres_db_real, _session_on(last_month_day, "last_month_session", "alice"))
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "today_session", "alice"))
    # Checked before the day and between its batches
    checks = iter([False, False])

    assert await async_postgres_db_real.calculate_metrics_dates(should_stop=lambda: next(checks, True)) is None
    await async_postgres_db_real.calculate_metrics()

    user_metrics_rows = await _stored_user_metrics_rows(async_postgres_db_real)
    month_row = user_metrics_rows[("monthly", last_month_day.replace(day=1))]
    day_row = user_metrics_rows[("daily", last_month_day)]
    assert (_user_metrics_sessions_count(month_row), month_row["total_tokens"]) == (1, day_row["total_tokens"])
    assert day_row["total_tokens"] == 15


@pytest.mark.asyncio
async def test_get_metrics_totals_reads_an_open_month_from_its_days(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a month whose user metrics row a stopped calculation left open is totalled from its days"""
    last_month_day = _month_start(0) - timedelta(days=1)
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "today_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    await _persist(async_postgres_db_real, _session_on(last_month_day, "last_month_session", "alice"))
    # Checked before the day and between its batches, then before the next day or the months
    checks = iter([False, False])

    assert await async_postgres_db_real.calculate_metrics_dates(should_stop=lambda: next(checks, True)) is None

    totals, _ = await async_postgres_db_real.get_metrics_totals(
        starting_date=last_month_day.replace(day=1), ending_date=last_month_day, fields=["total_tokens"]
    )
    assert totals["total_tokens"] == 15


@pytest.mark.asyncio
async def test_calculate_metrics_rebuild_from_reopens_the_days_while_another_process_calculates(
    async_postgres_db_real: AsyncPostgresDb,
):
    """Ensure rebuild_from reopens its days even when another process holds the metrics refresh, so the next
    calculation rebuilds them"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    refreshes_table = await async_postgres_db_real._get_table("metrics_refreshes")
    assert await async_postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process") is not None

    assert await async_postgres_db_real.calculate_metrics(rebuild_from=_utc_date(3)) is None
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]["completed"] is False

    await async_postgres_db_real._release_metrics_refresh(refreshes_table, "other_process", stopped=True)
    await async_postgres_db_real.calculate_metrics()
    assert (await _stored_user_metrics_rows(async_postgres_db_real))[("daily", _utc_date(3))]["completed"] is True


@pytest.mark.asyncio
async def test_get_metrics_never_runs_a_first_calculation(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a read never waits for a first calculation, and refreshes once one has finished"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))

    assert await async_postgres_db_real.get_metrics() == ([], None)
    assert await async_postgres_db_real.get_metrics_refresh_status() is None

    await async_postgres_db_real.calculate_metrics()
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "bob_session", "bob"))
    # The last refresh on read was a minute ago
    async_postgres_db_real._metrics_refreshed_at = 0.0
    metrics, _ = await async_postgres_db_real.get_metrics()
    assert [(row["date"], row["user_id"]) for row in metrics] == [(_utc_date(2), "alice"), (_utc_date(0), "bob")]


@pytest.mark.asyncio
async def test_get_metrics_returns_the_latest_update_of_every_day(async_postgres_db_real: AsyncPostgresDb):
    """Ensure the latest updated_at a read returns is of every day of the owner, as agno_metrics returned it, not
    only of the date range read"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_old_session", "alice"))
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "alice_session", "alice"))
    await async_postgres_db_real.calculate_metrics()
    user_metrics_table = await async_postgres_db_real._get_table("user_metrics")
    later = int(time.time()) + 100
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            user_metrics_table.update()
            .where(
                user_metrics_table.c.aggregation_period == "daily",
                user_metrics_table.c.date == _utc_date(0),
                user_metrics_table.c.user_id == "alice",
            )
            .values(updated_at=later)
        )

    metrics, latest_updated_at = await async_postgres_db_real.get_metrics(
        starting_date=_utc_date(3), ending_date=_utc_date(3), user_id="alice"
    )
    assert [row["date"] for row in metrics] == [_utc_date(3)]
    assert latest_updated_at == later


@pytest.mark.asyncio
async def test_component_metrics_tables_for_a_long_session_table(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a session table name long enough to push the component metrics table and index names past 63
    characters still builds the metrics tables"""
    long_db = AsyncPostgresDb(
        db_engine=async_postgres_db_real.db_engine,
        db_schema="test_schema",
        session_table="metrics_sessions_with_a_name_of_46_characters_",
        runs_table="long_name_runs",
    )
    try:
        await _persist(long_db, _session_on(_utc_date(2), "alice_session", "alice"))
        assert await long_db.calculate_metrics() is not None
        assert (await _stored_user_metrics_rows(long_db))[("daily", _utc_date(2))]["agent_runs_count"] == 1
    finally:
        for table_type in ["component_metrics", "user_metrics", "metrics_refreshes", "runs", "sessions"]:
            table = await long_db._get_table(table_type)
            if table is not None:
                async with long_db.db_engine.begin() as conn:
                    await conn.run_sync(table.drop)


@pytest.mark.asyncio
async def test_get_metrics_of_a_database_agentos_calculates_never_calculates(async_postgres_db_real: AsyncPostgresDb):
    """Ensure a read of a database whose metrics AgentOS calculates in the background calculates nothing itself"""
    async_postgres_db_real.stop_metrics_refresh_on_read()
    await _persist(async_postgres_db_real, _session_on(_utc_date(0), "alice_session", "alice"))

    assert await async_postgres_db_real.get_metrics() == ([], None)
    assert await async_postgres_db_real.get_metrics_refresh_status() is None


@pytest.mark.asyncio
async def test_a_cancelled_calculation_releases_the_lock(async_postgres_db_real: AsyncPostgresDb, monkeypatch):
    """Ensure a calculation cancelled mid-build, as on shutdown, releases the metrics refresh instead of holding it"""
    await _persist(async_postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(async_postgres_db_real, "_calculate_date_metrics", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await async_postgres_db_real.calculate_metrics_dates()

    refresh_status = await async_postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)
