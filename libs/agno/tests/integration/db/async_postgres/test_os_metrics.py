"""Integration tests for the OS Metrics related methods of the AsyncPostgresDb class"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pytest
import pytest_asyncio
from sqlalchemy import inspect, select, text

from agno.db.postgres import AsyncPostgresDb
from agno.db.utils import merge_os_metrics_totals, resolve_os_metrics_fields, total_os_metrics_records
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup_os_metrics_sessions_and_runs(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up OS metrics, session and run rows after each test"""
    yield

    try:
        for table_type in ("os_metrics", "runs", "sessions"):
            table = await async_postgres_db_real._get_table(table_type, create_table_if_not_found=True)
            async with async_postgres_db_real.async_session_factory() as session:
                await session.execute(table.delete())
                await session.commit()
    except Exception:
        pass  # Ignore cleanup errors


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


async def _persist(db: AsyncPostgresDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table.

    ``upsert_session`` stopped writing the runs column when runs were normalised out, so an
    OS metrics test that only called it would count no runs at all.
    """
    await db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        await db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


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


async def _stored_rows(db: AsyncPostgresDb) -> Dict[tuple, Dict]:
    """Every OS metrics row in the table, keyed by (date, user_id, agent_id, team_id, workflow_id)

    The total rows and month rows are left out: see ``_stored_total_rows``.
    """
    table = await db._get_table("os_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table).where(table.c.aggregation_period == "daily"))
        return {
            (row.date, row.user_id, row.agent_id, row.team_id, row.workflow_id): dict(row._mapping)
            for row in result.fetchall()
        }


async def _stored_total_rows(db: AsyncPostgresDb) -> Dict[tuple, Dict]:
    """Every total row and month row in the table, keyed by its date, period, owner and component"""
    table = await db._get_table("os_metrics", create_table_if_not_found=True)
    async with db.async_session_factory() as sess:
        result = await sess.execute(select(table).where(table.c.aggregation_period != "daily"))
        return {
            (
                row.date,
                row.aggregation_period,
                row.user_id,
                row.agent_id,
                row.team_id,
                row.workflow_id,
            ): dict(row._mapping)
            for row in result.fetchall()
        }


@pytest.fixture
def sample_sessions_for_os_metrics() -> List:
    """Fixture returning the sessions of one past day, plus one of today.

    Yesterday: alice has an agent session with a completed run and an error run, bob has an
    agent session and a team session whose team run has a member run, and one agent session
    has no owner. Today: alice has one more agent session.
    """
    base_time = _noon_utc(1)

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

# The rows yesterday's sessions produce, one per owner and component
YESTERDAY_ROW_KEYS = [
    ("alice", "agent-1", "", ""),
    ("bob", "agent-1", "", ""),
    ("bob", "", "team-1", ""),
    ("bob", "agent-2", "", ""),
    ("", "agent-1", "", ""),
]


@pytest.mark.asyncio
async def test_os_metrics_table_creation(async_postgres_db_real: AsyncPostgresDb):
    """Ensure the OS metrics table is created with its columns, unique constraint and indexes"""
    os_metrics_table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)

    assert os_metrics_table is not None
    assert os_metrics_table.name == async_postgres_db_real.os_metrics_table_name
    assert os_metrics_table.schema == async_postgres_db_real.db_schema

    column_names = [col.name for col in os_metrics_table.columns]
    expected_columns = [
        "id",
        "date",
        "aggregation_period",
        "user_id",
        "agent_id",
        "team_id",
        "workflow_id",
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

    async with async_postgres_db_real.db_engine.connect() as conn:
        unique_constraints = {
            constraint["name"]: constraint["column_names"]
            for constraint in await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_unique_constraints(
                    os_metrics_table.name, schema=os_metrics_table.schema
                )
            )
        }
        indexes = {
            index["name"]: index["column_names"]
            for index in await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_indexes(os_metrics_table.name, schema=os_metrics_table.schema)
            )
        }
    assert unique_constraints[f"{os_metrics_table.name}_uq_os_metrics_user_date_period_component"] == [
        "user_id",
        "date",
        "aggregation_period",
        "agent_id",
        "team_id",
        "workflow_id",
    ]
    assert indexes[f"idx_{os_metrics_table.name}_date"] == ["date"]


@pytest.mark.asyncio
async def test_calculate_os_metrics_no_sessions(async_postgres_db_real: AsyncPostgresDb):
    """Ensure the calculate_os_metrics method returns None when there are no sessions"""
    result = await async_postgres_db_real.calculate_os_metrics()

    assert result is None


@pytest.mark.asyncio
async def test_calculate_os_metrics_skips_a_rebuild_already_running(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure the lazy rebuild behind a read writes nothing while another process holds the rebuild lock"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)

    # Another process is rebuilding: its transaction holds the lock until it commits
    async with async_postgres_db_real.async_session_factory() as other, other.begin():
        await other.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('agno_os_metrics'), hashtext(:table_name))"),
            {"table_name": table.fullname},
        )

        assert await async_postgres_db_real._calculate_os_metrics(wait_for_rebuild=False) is None
        assert await _stored_rows(async_postgres_db_real) == {}
        # A skipped rebuild does not count as a refresh, so the next read tries again
        assert async_postgres_db_real._os_metrics_refreshed_at == 0.0

    # Nobody holds the lock any more, so the same call rebuilds
    result = await async_postgres_db_real._calculate_os_metrics(wait_for_rebuild=False)
    assert result is not None
    assert len(await _stored_rows(async_postgres_db_real)) == len(YESTERDAY_ROW_KEYS) + 1


@pytest.mark.asyncio
async def test_calculate_os_metrics_skips_messages_carried_over_from_history(async_postgres_db_real):
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
                created_at=_noon_utc(1),
            )
        ],
        created_at=_noon_utc(1),
    )
    await _persist(async_postgres_db_real, session)

    await async_postgres_db_real.calculate_os_metrics()

    row = (await _stored_rows(async_postgres_db_real))[(_utc_date(1), "alice", "agent-1", "", "")]
    assert row["duration_metrics"]["model_calls_count"] == 1
    assert row["duration_metrics"]["total_model_call_ms"] == 1200
    assert row["duration_metrics"]["model_call_ms_buckets"] == {"le_1200": 1}


@pytest.mark.asyncio
async def test_calculate_os_metrics(async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics):
    """Ensure calculate_os_metrics writes one row per owner and component for each day"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)

    result = await async_postgres_db_real.calculate_os_metrics()
    assert result is not None
    # Yesterday's rows with its total row, and today's row
    assert len(result) == len(YESTERDAY_ROW_KEYS) + 2

    yesterday = _utc_date(1)
    today = _utc_date(0)
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert len(stored_rows) == len(YESTERDAY_ROW_KEYS) + 1

    # Rows are unique by day, owner and component, so every row can be found by that key
    for key in YESTERDAY_ROW_KEYS:
        assert (yesterday, *key) in stored_rows
    today_row = stored_rows[(today, "alice", "agent-1", "", "")]

    # A past day's rows are complete, today's are not
    assert all(row["completed"] is True for row in stored_rows.values() if row["date"] == yesterday)
    assert today_row["completed"] is False
    assert today_row["sessions_count"] == 1
    assert today_row["runs_count"] == 1

    alice_row = stored_rows[(yesterday, "alice", "agent-1", "", "")]
    assert alice_row["date"] == yesterday
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
    team_row = stored_rows[(yesterday, "bob", "", "team-1", "")]
    assert team_row["sessions_count"] == 1
    assert team_row["runs_count"] == 1
    assert team_row["model_metrics"][0]["team_id"] == "team-1"
    member_row = stored_rows[(yesterday, "bob", "agent-2", "", "")]
    assert member_row["sessions_count"] == 0
    assert member_row["runs_count"] == 1
    assert member_row["token_metrics"] == {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}

    unowned_row = stored_rows[(yesterday, "", "agent-1", "", "")]
    assert unowned_row["user_id"] == ""
    assert unowned_row["sessions_count"] == 1
    assert unowned_row["runs_count"] == 1


@pytest.mark.asyncio
async def test_calculate_os_metrics_rewrites_only_changed_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a rebuild leaves unchanged rows alone, rewrites a changed row and drops a stale one"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)

    result = await async_postgres_db_real.calculate_os_metrics()
    assert result is not None
    row_count = len(await _stored_rows(async_postgres_db_real))

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.update().values(updated_at=1))

    # Nothing changed: yesterday is complete so only today is rebuilt, and its row is not written
    today = _utc_date(0)
    alice_today_row_id = (today, "alice", "agent-1", "", "")
    result = await async_postgres_db_real.calculate_os_metrics()
    assert result is not None
    assert [(row["date"], row["user_id"], row["agent_id"], row["team_id"], row["workflow_id"]) for row in result] == [
        alice_today_row_id
    ]
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert len(stored_rows) == row_count
    assert all(row["updated_at"] == 1 for row in stored_rows.values())

    # One more run for alice's session today: only that row is rewritten
    alice_today_session = sample_sessions_for_os_metrics[4]
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
    await async_postgres_db_real.calculate_os_metrics()
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
    await async_postgres_db_real.calculate_os_metrics()
    bob_today_row_id = (today, "bob", "agent-1", "", "")
    assert bob_today_row_id in await _stored_rows(async_postgres_db_real)

    assert await async_postgres_db_real.delete_session("bob_today_session") is True
    await async_postgres_db_real.calculate_os_metrics()
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert len(stored_rows) == row_count
    assert bob_today_row_id not in stored_rows


@pytest.mark.asyncio
async def test_get_os_metrics_by_date(async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics totals the rows of each day, for every owner or one"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    yesterday = _utc_date(1)
    today = _utc_date(0)

    # Every owner: one dict per day, oldest first, with every field
    metrics, latest_updated_at = await async_postgres_db_real.get_os_metrics(starting_date=yesterday, ending_date=today)
    assert latest_updated_at is not None
    assert [m["date"] for m in metrics] == [yesterday, today]
    yesterday_totals = metrics[0]
    assert set(yesterday_totals) == {
        "date",
        "sessions_count",
        "runs_count",
        "status_metrics",
        "token_metrics",
        "duration_metrics",
        "model_metrics",
        "duration_buckets",
    }
    assert yesterday_totals["sessions_count"] == 4
    assert yesterday_totals["runs_count"] == 6
    assert yesterday_totals["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert yesterday_totals["token_metrics"] == {"input_tokens": 385, "output_tokens": 185, "total_tokens": 570}
    assert yesterday_totals["duration_metrics"] == {
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
        yesterday_totals["model_metrics"], key=lambda m: (m.get("agent_id", ""), m.get("team_id", ""))
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
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert latest_updated_at == max(row["updated_at"] for row in stored_rows.values())

    # One owner: only bob's rows are summed
    metrics, _ = await async_postgres_db_real.get_os_metrics(starting_date=yesterday, ending_date=today, user_id="bob")
    assert [m["date"] for m in metrics] == [yesterday]
    assert metrics[0]["sessions_count"] == 2
    assert metrics[0]["runs_count"] == 3
    assert metrics[0]["token_metrics"] == {"input_tokens": 270, "output_tokens": 130, "total_tokens": 400}

    # The empty owner: only the unowned rows
    metrics, _ = await async_postgres_db_real.get_os_metrics(starting_date=yesterday, ending_date=today, user_id="")
    assert [m["date"] for m in metrics] == [yesterday]
    assert metrics[0]["sessions_count"] == 1
    assert metrics[0]["runs_count"] == 1
    assert metrics[0]["token_metrics"] == {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}


@pytest.mark.asyncio
async def test_get_os_metrics_fields(async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics returns only the fields asked for, with the buckets only on request"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    yesterday = _utc_date(1)

    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=yesterday, fields=["duration_metrics"]
    )
    assert set(metrics[0]) == {"date", "duration_metrics"}
    assert not any(key.endswith("_buckets") for key in metrics[0]["duration_metrics"])

    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=yesterday, fields=["duration_metrics", "duration_buckets"]
    )
    assert set(metrics[0]) == {"date", "duration_metrics", "duration_buckets"}
    assert not any(key.endswith("_buckets") for key in metrics[0]["duration_metrics"])
    assert metrics[0]["duration_buckets"] == {
        "duration_ms_buckets": {"le_1000": 1, "le_2000": 1, "le_3000": 1, "le_4000": 1},
        "time_to_first_token_ms_buckets": {"le_500": 1, "le_1000": 1},
        "model_call_ms_buckets": {"le_1500": 1, "le_2500": 1},
    }

    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=yesterday, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [{"date": yesterday, "sessions_count": 4, "runs_count": 6}]

    with pytest.raises(ValueError):
        await async_postgres_db_real.get_os_metrics(
            starting_date=yesterday, ending_date=yesterday, fields=["users_count"]
        )


@pytest.mark.asyncio
async def test_get_os_metrics_refreshes_rows(async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics):
    """Ensure get_os_metrics builds the rows itself when they have not been refreshed yet"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    assert await _stored_rows(async_postgres_db_real) == {}

    yesterday = _utc_date(1)
    today = _utc_date(0)
    async_postgres_db_real._os_metrics_refreshed_at = 0
    metrics, latest_updated_at = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=today, fields=["sessions_count"]
    )

    assert latest_updated_at is not None
    assert metrics == [{"date": yesterday, "sessions_count": 4}, {"date": today, "sessions_count": 1}]
    assert len(await _stored_rows(async_postgres_db_real)) == len(YESTERDAY_ROW_KEYS) + 1


@pytest.mark.asyncio
async def test_get_os_metrics_no_rows(async_postgres_db_real: AsyncPostgresDb):
    """Ensure get_os_metrics returns nothing when there are no sessions"""
    metrics, latest_updated_at = await async_postgres_db_real.get_os_metrics(
        starting_date=_utc_date(1), ending_date=_utc_date(0)
    )

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


@pytest.mark.asyncio
async def test_os_metrics_multiple_days(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_day_sessions_for_os_metrics
):
    """Ensure sessions on two days produce rows on both, and a one-day window returns only that day"""
    for session in sample_multi_day_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)

    result = await async_postgres_db_real.calculate_os_metrics()
    assert result is not None
    # Each day's row, with the day's total row
    assert len(result) == 4

    first_day = _utc_date(3)
    second_day = _utc_date(2)
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert {row["date"] for row in stored_rows.values()} == {first_day, second_day}

    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=first_day, ending_date=second_day, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [
        {"date": first_day, "sessions_count": 2, "runs_count": 2},
        {"date": second_day, "sessions_count": 1, "runs_count": 1},
    ]

    metrics, _ = await async_postgres_db_real.get_os_metrics(
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


async def _stored_month_rows(db: AsyncPostgresDb) -> Dict[tuple, Dict]:
    """Every month row in the table, keyed as in ``_stored_total_rows``"""
    return {key: row for key, row in (await _stored_total_rows(db)).items() if key[1] in ("monthly", "monthly_total")}


async def _sessions_counts(db: AsyncPostgresDb, day, user_id) -> List[int]:
    """The sessions_count of each day get_os_metrics returns for the given day, for every owner or one"""
    metrics, _ = await db.get_os_metrics(starting_date=day, ending_date=day, user_id=user_id, fields=["sessions_count"])
    return [day_totals["sessions_count"] for day_totals in metrics]


async def _total_sessions_count(db: AsyncPostgresDb, starting_date, ending_date, user_id=None) -> int:
    """The sessions_count get_os_metrics_totals returns for the date range, for every owner or one"""
    totals, _ = await db.get_os_metrics_totals(
        starting_date=starting_date, ending_date=ending_date, user_id=user_id, fields=["sessions_count"]
    )
    return totals["sessions_count"]


@pytest.mark.asyncio
async def test_calculate_os_metrics_writes_a_total_row_for_a_completed_day(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a completed day gets one total row for every owner, and an open day none"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    yesterday = _utc_date(1)
    stored_rows = await _stored_rows(async_postgres_db_real)
    total_rows = await _stored_total_rows(async_postgres_db_real)
    assert set(total_rows) == {(yesterday, "daily_total", "", "", "", "")}

    day_row = total_rows[(yesterday, "daily_total", "", "", "", "")]
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
    assert day_row["updated_at"] == max(row["updated_at"] for row in stored_rows.values() if row["date"] == yesterday)


@pytest.mark.asyncio
async def test_get_os_metrics_reads_a_completed_day_from_its_total_row(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a read equals the sum of the rows, with a completed day read from its total row for every owner"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    yesterday = _utc_date(1)
    today = _utc_date(0)
    stored_rows = list((await _stored_rows(async_postgres_db_real)).values())
    fields = resolve_os_metrics_fields(None)

    # Every owner, then one owner: the same totals as the rows add up to
    metrics, latest_updated_at = await async_postgres_db_real.get_os_metrics(starting_date=yesterday, ending_date=today)
    expected, expected_updated_at = total_os_metrics_records(stored_rows, fields)
    assert _comparable(metrics) == _comparable(expected)
    assert latest_updated_at == expected_updated_at
    metrics, latest_updated_at = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=today, user_id="bob"
    )
    expected, expected_updated_at = total_os_metrics_records(
        [row for row in stored_rows if row["user_id"] == "bob"], fields
    )
    assert _comparable(metrics) == _comparable(expected)
    assert latest_updated_at == expected_updated_at

    # Change every row: for every owner yesterday is still read from its total row and today from its rows
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.update().where(table.c.aggregation_period == "daily").values(sessions_count=50))
    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=today, fields=["sessions_count"]
    )
    assert metrics == [{"date": yesterday, "sessions_count": 4}, {"date": today, "sessions_count": 50}]
    # One owner is read from that owner's rows on every day: bob has three rows yesterday
    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=today, user_id="bob", fields=["sessions_count"]
    )
    assert metrics == [{"date": yesterday, "sessions_count": 150}]


@pytest.mark.asyncio
async def test_get_os_metrics_reads_a_day_without_a_total_row_from_its_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure a day whose total row is missing is read from its rows"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    yesterday = _utc_date(1)
    today = _utc_date(0)
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.delete().where(table.c.aggregation_period == "daily_total"))

    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=yesterday, ending_date=today, fields=["sessions_count"]
    )
    assert metrics == [{"date": yesterday, "sessions_count": 4}, {"date": today, "sessions_count": 1}]


@pytest.mark.asyncio
async def test_get_os_metrics_never_reads_a_total_row_for_one_owner(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure one owner's read uses only that owner's rows, and the empty owner's never the row of every owner"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    yesterday = _utc_date(1)
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            table.update().where(table.c.aggregation_period == "daily_total").values(sessions_count=1000)
        )

    assert await _sessions_counts(async_postgres_db_real, yesterday, None) == [1000]
    assert await _sessions_counts(async_postgres_db_real, yesterday, "alice") == [1]
    assert await _sessions_counts(async_postgres_db_real, yesterday, "bob") == [2]
    # The unowned row, not the total row of every owner, which also has an empty user_id
    assert await _sessions_counts(async_postgres_db_real, yesterday, "") == [1]
    assert await _sessions_counts(async_postgres_db_real, yesterday, "carol") == []


@pytest.mark.asyncio
async def test_calculate_os_metrics_writes_month_rows_for_a_completed_month(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a completed month gets a total row and a row per owner and component, and this month none"""
    for session in sample_multi_month_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    stored_rows = await _stored_rows(async_postgres_db_real)
    month_rows = await _stored_month_rows(async_postgres_db_real)
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
    await async_postgres_db_real.calculate_os_metrics()
    assert await _stored_month_rows(async_postgres_db_real) == month_rows


@pytest.mark.asyncio
async def test_calculate_os_metrics_calculates_a_month_once_none_of_its_days_is_open(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a month with an open day gets no month rows, and a later rebuild writes them once it has none"""
    for session in sample_multi_month_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)

    # The first month loses its month rows and has a day still open
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            table.delete().where(
                table.c.date == first_month, table.c.aggregation_period.in_(["monthly", "monthly_total"])
            )
        )
        await sess.execute(
            table.update()
            .where(table.c.date == first_month, table.c.aggregation_period == "daily", table.c.user_id == "alice")
            .values(completed=False)
        )
    await async_postgres_db_real.calculate_os_metrics()
    assert set(await _stored_month_rows(async_postgres_db_real)) == {
        (second_month, "monthly_total", "", "", "", ""),
        (second_month, "monthly", "bob", "agent-1", "", ""),
    }

    # None of its days is rebuilt again, and the next rebuild still calculates it
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.update().where(table.c.date == first_month).values(completed=True))
    result = await async_postgres_db_real.calculate_os_metrics()
    assert result is not None
    assert {row["date"] for row in result} == {_utc_date(0)}
    assert set(await _stored_month_rows(async_postgres_db_real)) == {
        (first_month, "monthly_total", "", "", "", ""),
        (first_month, "monthly", "", "agent-1", "", ""),
        (first_month, "monthly", "alice", "agent-1", "", ""),
        (first_month, "monthly", "bob", "agent-1", "", ""),
        (second_month, "monthly_total", "", "", "", ""),
        (second_month, "monthly", "bob", "agent-1", "", ""),
    }


@pytest.mark.asyncio
async def test_get_os_metrics_totals(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure the totals of a date range equal its days' totals summed, for every owner or one"""
    for session in sample_multi_month_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

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
            totals, latest_updated_at = await async_postgres_db_real.get_os_metrics_totals(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            metrics, expected_updated_at = await async_postgres_db_real.get_os_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            assert _comparable(totals) == _comparable(merge_os_metrics_totals(metrics, fields))
            assert latest_updated_at == expected_updated_at

    totals, _ = await async_postgres_db_real.get_os_metrics_totals(
        starting_date=first_month, ending_date=today, fields=["sessions_count", "runs_count"]
    )
    assert totals == {"sessions_count": 6, "runs_count": 6}
    totals, latest_updated_at = await async_postgres_db_real.get_os_metrics_totals(
        starting_date=first_month, ending_date=today, user_id="carol", fields=["sessions_count", "model_metrics"]
    )
    assert totals == {"sessions_count": 0, "model_metrics": []}
    assert latest_updated_at is None


@pytest.mark.asyncio
async def test_get_os_metrics_totals_reads_a_whole_month_from_its_month_rows(
    async_postgres_db_real: AsyncPostgresDb, sample_multi_month_sessions_for_os_metrics
):
    """Ensure a month inside the date range is read from its month rows, each owner from their own"""
    for session in sample_multi_month_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.calculate_os_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(
            table.update()
            .where(table.c.date == first_month, table.c.aggregation_period == "monthly_total")
            .values(sessions_count=1000)
        )
        await sess.execute(
            table.update()
            .where(table.c.date == first_month, table.c.aggregation_period == "monthly", table.c.user_id == "bob")
            .values(sessions_count=500)
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
    # One owner's month comes from that owner's month rows, and the empty owner's never from the row of every owner
    assert (
        await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1), "alice") == 2
    )
    assert (
        await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1), "bob") == 500
    )
    assert await _total_sessions_count(async_postgres_db_real, first_month, second_month - timedelta(days=1), "") == 1
    # The read of each day never uses a month row
    metrics, _ = await async_postgres_db_real.get_os_metrics(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), fields=["sessions_count"]
    )
    assert metrics == [
        {"date": first_month, "sessions_count": 2},
        {"date": first_month + timedelta(days=14), "sessions_count": 2},
    ]


@pytest.mark.asyncio
async def test_refresh_os_metrics_reports_what_changed(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
    """Ensure refresh_os_metrics reports a change only when the rebuild wrote or deleted a row"""
    for session in sample_sessions_for_os_metrics:
        await _persist(async_postgres_db_real, session)

    previous_updated_at, updated_at, changed = await async_postgres_db_real.refresh_os_metrics()
    assert previous_updated_at is None
    assert updated_at is not None
    assert changed is True

    # Nothing new: no row is written, and the table was last updated when it was before
    assert await async_postgres_db_real.refresh_os_metrics() == (updated_at, updated_at, False)

    # One more run today: reported even when it lands in the same second as the rebuild before it
    alice_today_session = sample_sessions_for_os_metrics[4]
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
    previous_updated_at, latest_updated_at, changed = await async_postgres_db_real.refresh_os_metrics()
    assert previous_updated_at == updated_at
    assert latest_updated_at >= updated_at
    assert changed is True
    assert (await _stored_rows(async_postgres_db_real))[(_utc_date(0), "alice", "agent-1", "", "")]["runs_count"] == 2


@pytest.mark.asyncio
async def test_refresh_os_metrics_after_a_delete_moves_the_day(
    async_postgres_db_real: AsyncPostgresDb, sample_sessions_for_os_metrics
):
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
        await _persist(async_postgres_db_real, session)
    await async_postgres_db_real.refresh_os_metrics()

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    table = await async_postgres_db_real._get_table("os_metrics", create_table_if_not_found=True)
    async with async_postgres_db_real.async_session_factory() as sess, sess.begin():
        await sess.execute(table.update().values(updated_at=1))

    assert await async_postgres_db_real.delete_session("bob_today_session") is True
    previous_updated_at, latest_updated_at, changed = await async_postgres_db_real.refresh_os_metrics()
    assert previous_updated_at == 1
    assert latest_updated_at != 1
    assert changed is True

    # Bob's row is gone, and alice's row of the day is rewritten, so a read of the day reports the new time
    today = _utc_date(0)
    metrics, read_updated_at = await async_postgres_db_real.get_os_metrics(
        starting_date=today, ending_date=today, fields=["sessions_count", "runs_count"]
    )
    assert metrics == [{"date": today, "sessions_count": 1, "runs_count": 1}]
    assert read_updated_at == latest_updated_at
    stored_rows = await _stored_rows(async_postgres_db_real)
    assert all(row["updated_at"] == 1 for row in stored_rows.values() if row["date"] != today)
