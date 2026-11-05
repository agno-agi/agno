"""Integration tests for the component metrics related methods of the PostgresDb class"""

import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

import pytest
from sqlalchemy import inspect, null, select, text

from agno.db.base import SessionType
from agno.db.postgres.postgres import PostgresDb
from agno.db.postgres.schemas import (
    AGGREGATE_METRICS_TABLE_SCHEMA,
    COMPONENT_METRICS_TABLE_SCHEMA,
    METRICS_REFRESHES_TABLE_SCHEMA,
)
from agno.db.postgres.utils import build_component_metrics_runs_query, reopen_metrics_day, upsert_aggregate_metrics_row
from agno.db.utils import (
    AGGREGATE_METRICS_COUNT_COLUMNS,
    METRICS_STOPPED_ERROR,
    METRICS_TOKEN_DETAILS_FIELDS,
    METRICS_TOKEN_FIELDS,
    calculate_date_component_metrics,
    list_metrics_totals_models,
    merge_metrics_totals,
    metrics_day_completed,
    resolve_metrics_fields,
)
from agno.metrics import MessageMetrics, ModelMetrics, RunMetrics
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession


@pytest.fixture(autouse=True)
def cleanup_component_metrics_sessions_and_runs(postgres_db_real: PostgresDb):
    """Fixture to clean-up component metrics, session and run rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            for table_type in [
                "component_metrics",
                "aggregate_metrics",
                "metrics_refreshes",
                "metrics",
                "runs",
                "sessions",
            ]:
                table = postgres_db_real._get_table(table_type, create_table_if_not_found=True)
                session.execute(table.delete())
            session.commit()
        except Exception:
            session.rollback()


@pytest.fixture
def legacy_runs_column(postgres_db_real: PostgresDb):
    """Fixture adding the sessions table's legacy runs column, and dropping it after the test"""
    schema_version = postgres_db_real.get_latest_schema_version(postgres_db_real.session_table_name)
    postgres_db_real._get_table("sessions", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN runs JSONB"))
    yield

    postgres_db_real.upsert_schema_version(postgres_db_real.session_table_name, schema_version)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(text("ALTER TABLE test_schema.test_sessions DROP COLUMN runs"))


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


def _persist(db: PostgresDb, session) -> None:
    """Store a session the way v3 does: the row, then each run in the runs table.

    ``upsert_session`` stopped writing the runs column when runs were normalised out, so a
    component metrics test that only called it would count no runs at all.
    """
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _store_legacy_runs(db: PostgresDb, runs: List[Dict]) -> PostgresDb:
    """Keep the runs in the sessions table's legacy runs column, and return a new instance that reads them.

    The legacy column is read only before the v3.0.0 migration is stamped.
    """
    with db.Session() as sess, sess.begin():
        sess.execute(
            text("UPDATE test_schema.test_sessions SET runs = CAST(:runs AS JSONB)"), {"runs": json.dumps(runs)}
        )
    db.upsert_schema_version(db.session_table_name, "2.5.0")
    # A new instance, so the sessions table is read with its legacy column
    return PostgresDb(db_engine=db.db_engine, db_schema="test_schema", session_table="test_sessions")


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
    """Every row of agno_component_metrics, keyed by (date, user_id, component_type, component_id)."""
    table = db._get_table("component_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.date, row.user_id, row.component_type, row.component_id): dict(row._mapping)
            for row in sess.execute(select(table).where(table.c.aggregation_period == "daily")).fetchall()
        }


def _stored_aggregate_metrics_rows(db: PostgresDb) -> Dict[tuple, Dict]:
    """Every day and month everyone row of agno_aggregate_metrics, keyed by (aggregation_period, date).

    The user rows are left out.
    """
    table = db._get_table("aggregate_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        return {
            (row.aggregation_period, row.date): dict(row._mapping)
            for row in sess.execute(select(table).where(table.c.user_id == "")).fetchall()
        }


def _aggregate_metrics_sessions_count(row: Dict) -> int:
    """The sessions of every type a row of agno_aggregate_metrics keeps."""
    return row["agent_sessions_count"] + row["team_sessions_count"] + row["workflow_sessions_count"]


def _merged_totals(rows: List[Dict], fields: List[str]) -> Dict:
    """The totals a read returns for the given rows of agno_component_metrics: the root runs are those no other run
    started."""
    return {
        **list_metrics_totals_models(merge_metrics_totals(rows, fields)),
        "root_runs_count": sum(row["runs_count"] for row in rows if not row["parent_component_id"]),
    }


def _models_by_provider(models: List[Dict]) -> Dict[str, Dict[str, Dict]]:
    """The models a read lists, counted per provider and model as a row of agno_component_metrics keeps them."""
    by_provider: Dict[str, Dict[str, Dict]] = {}
    for model in models:
        by_provider.setdefault(model["model_provider"], {})[model["model_id"]] = {"count": model["count"]}
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


def _sessions_counts(db: PostgresDb, day: date, user_id: Optional[str]) -> List[int]:
    """The sessions_count of each day get_component_metrics returns for the given day, for every owner or one."""
    metrics, _ = db.get_component_metrics(
        starting_date=day, ending_date=day, user_id=user_id, fields=["sessions_count"]
    )
    return [day_totals["sessions_count"] for day_totals in metrics]


def _total_sessions_count(db: PostgresDb, starting_date: date, ending_date: date, user_id: Optional[str] = None) -> int:
    """The sessions_count get_metrics_totals returns for the date range, for every owner or one."""
    totals, _ = db.get_metrics_totals(
        starting_date=starting_date, ending_date=ending_date, user_id=user_id, fields=["sessions_count"]
    )
    return totals["sessions_count"]


def _day_versions(db: PostgresDb, starting_date: date, ending_date: date) -> Dict[str, int]:
    """The version of each day's everyone row of agno_aggregate_metrics in the date range."""
    table = db._get_table("aggregate_metrics", create_table_if_not_found=True)
    with db.Session() as sess:
        rows = sess.execute(
            select(table.c.date, table.c.version).where(
                table.c.aggregation_period == "daily",
                table.c.user_id == "",
                table.c.date >= starting_date,
                table.c.date <= ending_date,
            )
        ).fetchall()
    return {f"daily {row.date.isoformat()}": row.version for row in rows}


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


def test_component_metrics_table_creation(postgres_db_real: PostgresDb):
    """Ensure the metrics tables are created with their columns, primary keys and indexes"""
    component_metrics_table = postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics", create_table_if_not_found=True)
    refreshes_table = postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)

    assert component_metrics_table.name == postgres_db_real.component_metrics_table_name
    assert aggregate_metrics_table.name == postgres_db_real.aggregate_metrics_table_name
    assert refreshes_table.name == postgres_db_real.metrics_refreshes_table_name
    assert component_metrics_table.schema == aggregate_metrics_table.schema == postgres_db_real.db_schema

    assert [col.name for col in component_metrics_table.columns] == [
        column for column in COMPONENT_METRICS_TABLE_SCHEMA if not column.startswith("_")
    ]
    assert {col.name for col in aggregate_metrics_table.columns} == set(AGGREGATE_METRICS_TABLE_SCHEMA)
    assert [col.name for col in refreshes_table.columns] == list(METRICS_REFRESHES_TABLE_SCHEMA)
    assert set(METRICS_TOKEN_FIELDS) - {*METRICS_TOKEN_DETAILS_FIELDS, "audio_total_tokens"} | {"token_details"} | set(
        AGGREGATE_METRICS_COUNT_COLUMNS
    ) <= set(AGGREGATE_METRICS_TABLE_SCHEMA)
    assert "sessions_count" not in AGGREGATE_METRICS_TABLE_SCHEMA

    inspector = inspect(postgres_db_real.db_engine)
    assert inspector.get_pk_constraint(component_metrics_table.name, schema=component_metrics_table.schema)[
        "constrained_columns"
    ] == [
        "aggregation_period",
        "date",
        "user_id",
        "component_type",
        "component_id",
        "parent_component_id",
        "root_component_id",
    ]
    assert inspector.get_pk_constraint(aggregate_metrics_table.name, schema=aggregate_metrics_table.schema)[
        "constrained_columns"
    ] == [
        "aggregation_period",
        "date",
        "user_id",
    ]
    assert inspector.get_pk_constraint(refreshes_table.name, schema=refreshes_table.schema)["constrained_columns"] == [
        "id"
    ]
    indexes = {
        index["name"]: index["column_names"]
        for index in inspector.get_indexes(component_metrics_table.name, schema=component_metrics_table.schema)
    }
    assert indexes[f"idx_{component_metrics_table.name}_user_id_date"] == ["user_id", "date"]


def test_calculate_metrics_skips_a_rebuild_already_running(
    postgres_db_real: PostgresDb, sample_sessions_for_component_metrics
):
    """Ensure one process claims the metrics refresh at a time, and calculate_metrics writes nothing while another
    process holds it"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    refreshes_table = postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)

    # Another process is calculating: it holds the metrics refresh until it releases it
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process") is not None
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "second_process") is None
    assert postgres_db_real.calculate_metrics() is None
    assert _stored_rows(postgres_db_real) == {}
    assert _stored_aggregate_metrics_rows(postgres_db_real) == {}

    # The other process stopped and released it, so the same call calculates
    postgres_db_real._release_metrics_refresh(refreshes_table, "other_process", stopped=True)
    result = postgres_db_real.calculate_metrics()
    assert result is not None
    assert len(_stored_rows(postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


def test_claim_metrics_refresh_returns_while_another_process_writes_a_day(postgres_db_real: PostgresDb):
    """Ensure a claim returns None, instead of waiting, while the transaction of another process's day keeps the row of
    the metrics refreshes table locked"""
    refreshes_table = postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process") is not None

    with postgres_db_real.db_engine.connect() as conn, conn.begin():
        assert postgres_db_real._heartbeat_metrics_refresh(conn, refreshes_table, "other_process")
        assert postgres_db_real._claim_metrics_refresh(refreshes_table, "second_process") is None


def test_calculate_metrics_skips_messages_carried_over_from_history_or_copied_by_a_forked_run(
    postgres_db_real: PostgresDb,
):
    """Ensure a message carried over from an earlier run, or copied by a forked run from the run it was forked from, is
    not counted as a model call of this one"""
    history_session = AgentSession(
        session_id="history_session",
        agent_id="agent-2",
        user_id="alice",
        runs=[
            RunOutput(
                run_id="history_run",
                agent_id="agent-2",
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
    _persist(postgres_db_real, history_session)
    fork_session = _session_on(_utc_date(2), "fork_session", "alice")
    original = fork_session.runs[0]
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
    fork_session.runs.append(forked)
    _persist(postgres_db_real, fork_session)

    postgres_db_real.calculate_metrics()

    stored_rows = _stored_rows(postgres_db_real)
    history_row = stored_rows[(_utc_date(2), "alice", "agent", "agent-2")]
    assert history_row["model_calls_count"] == 1
    assert history_row["total_model_call_ms"] == 1200
    assert history_row["model_call_buckets"] == {"le_1200": 1}
    fork_row = stored_rows[(_utc_date(2), "alice", "agent", "agent-1")]
    assert (fork_row["runs_count"], fork_row["total_tokens"]) == (2, 40)
    assert (fork_row["model_calls_count"], fork_row["total_model_call_ms"]) == (2, 2000)


def test_calculate_metrics_skips_runs_a_forked_session_copied(postgres_db_real: PostgresDb):
    """Ensure a run copied into a forked session is not counted again, while the forked session is"""
    _persist(postgres_db_real, _session_on(_utc_date(2), "fork_session", "alice"))
    copied_session = _session_on(_utc_date(2), "copied_session", "alice")
    copied_session.runs[0].forked_from_session_id = "fork_session"
    _persist(postgres_db_real, copied_session)

    postgres_db_real.calculate_metrics()

    row = _stored_rows(postgres_db_real)[(_utc_date(2), "alice", "agent", "agent-1")]
    assert (row["sessions_count"], row["runs_count"], row["total_tokens"]) == (2, 1, 15)


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column(postgres_db_real: PostgresDb, legacy_runs_column):
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
    postgres_db_real.upsert_session(session)
    postgres_db_real.upsert_run(session.runs[0], session_id=session.session_id, user_id="alice", run_index=0)
    legacy_db = _store_legacy_runs(postgres_db_real, [run.to_dict() for run in session.runs])
    legacy_db.calculate_metrics()

    row = _stored_rows(legacy_db)[(_utc_date(6), "alice", "agent", "agent-1")]
    assert (row["sessions_count"], row["runs_count"], row["total_tokens"]) == (1, 2, 50)
    assert (row["model_calls_count"], row["total_model_call_ms"]) == (2, 2000)
    # The later run is counted on its own day, a day with no session
    assert _stored_aggregate_metrics_rows(legacy_db)[("daily", _utc_date(4))]["agent_runs_count"] == 1


def test_calculate_metrics_counts_a_legacy_member_run_kept_as_its_own_run_once(
    postgres_db_real: PostgresDb, legacy_runs_column
):
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
    postgres_db_real.upsert_session(session)
    postgres_db_real._get_table("runs", create_table_if_not_found=True)
    legacy_db = _store_legacy_runs(postgres_db_real, legacy_runs)
    legacy_db.calculate_metrics()

    aggregate_metrics_rows = _stored_aggregate_metrics_rows(legacy_db)
    assert aggregate_metrics_rows[("daily", _utc_date(6))]["total_tokens"] == 100
    assert aggregate_metrics_rows[("daily", _utc_date(4))]["total_tokens"] == 10


def test_calculate_metrics(postgres_db_real: PostgresDb, sample_sessions_for_component_metrics):
    """Ensure calculate_metrics writes one row per owner and component for each day"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)

    result = postgres_db_real.calculate_metrics()
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


def test_calculate_metrics_rewrites_only_changed_rows(
    postgres_db_real: PostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a rebuild leaves unchanged rows and versions alone, rewrites a changed row and drops a stale one"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)

    result = postgres_db_real.calculate_metrics()
    assert result is not None
    row_count = len(_stored_rows(postgres_db_real))
    versions = _day_versions(postgres_db_real, _utc_date(2), _utc_date(0))
    assert versions == {f"daily {_utc_date(days_ago).isoformat()}": 1 for days_ago in (2, 1, 0)}

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    table = postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().values(updated_at=1))

    # A session touched without a change: the past day is complete so only yesterday and today are rebuilt, and no
    # row is written
    sessions_table = postgres_db_real._get_table("sessions")
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(sessions_table.update().values(updated_at=int(time.time()) - 60))
    today = _utc_date(0)
    alice_today_row_id = (today, "alice", "agent", "agent-1")
    result = postgres_db_real.calculate_metrics()
    assert result is not None
    assert [(row["date"], row["user_id"]) for row in result] == [(today, "alice")]
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert all(row["updated_at"] == 1 for row in stored_rows.values())
    assert _day_versions(postgres_db_real, _utc_date(2), _utc_date(0)) == versions

    # One more run for alice's session today: only that row is rewritten, and only today's version moves
    alice_today_session = sample_sessions_for_component_metrics[4]
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
    postgres_db_real.calculate_metrics()
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert stored_rows[alice_today_row_id]["runs_count"] == 2
    assert stored_rows[alice_today_row_id]["updated_at"] != 1
    assert all(row["updated_at"] == 1 for row_id, row in stored_rows.items() if row_id != alice_today_row_id)
    today_key = f"daily {today.isoformat()}"
    assert _day_versions(postgres_db_real, _utc_date(2), _utc_date(0)) == {
        **versions,
        today_key: versions[today_key] + 1,
    }

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
    postgres_db_real.calculate_metrics()
    bob_today_row_id = (today, "bob", "agent", "agent-1")
    assert bob_today_row_id in _stored_rows(postgres_db_real)

    assert postgres_db_real.delete_session("bob_today_session") is True
    postgres_db_real.calculate_metrics()
    stored_rows = _stored_rows(postgres_db_real)
    assert len(stored_rows) == row_count
    assert bob_today_row_id not in stored_rows


def test_get_component_metrics_by_date(postgres_db_real: PostgresDb, sample_sessions_for_component_metrics):
    """Ensure get_component_metrics totals each day, every owner from the everyone rows and one owner from its rows"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    yesterday = _utc_date(1)
    today = _utc_date(0)

    # Every owner: one dict per day, oldest first, a day without traffic included, with every field
    metrics, latest_updated_at = postgres_db_real.get_component_metrics(starting_date=past_day, ending_date=today)
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

    # A one-day window returns only that day
    metrics, _ = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=past_day, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [{"date": past_day, "sessions_count": 4, "root_runs_count": 5}]

    # The latest updated_at of the window is the one returned
    aggregate_metrics_rows = _stored_aggregate_metrics_rows(postgres_db_real)
    assert latest_updated_at == max(
        row["updated_at"]
        for (period, row_date), row in aggregate_metrics_rows.items()
        if period == "daily" and past_day <= row_date <= today
    )

    # One owner: only bob's rows are summed, on the days bob has rows
    metrics, latest_updated_at = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, user_id="bob"
    )
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 2
    # Bob's member run was started by his team run
    assert metrics[0]["root_runs_count"] == 2
    assert (metrics[0]["input_tokens"], metrics[0]["output_tokens"], metrics[0]["total_tokens"]) == (270, 130, 400)
    stored_rows = _stored_rows(postgres_db_real)
    assert latest_updated_at == max(row["updated_at"] for row in stored_rows.values() if row["user_id"] == "bob")

    # The empty owner: only the unowned rows
    metrics, _ = postgres_db_real.get_component_metrics(starting_date=past_day, ending_date=today, user_id="")
    assert [m["date"] for m in metrics] == [past_day]
    assert metrics[0]["sessions_count"] == 1
    assert metrics[0]["root_runs_count"] == 1
    assert (metrics[0]["input_tokens"], metrics[0]["output_tokens"], metrics[0]["total_tokens"]) == (5, 5, 10)


def test_get_component_metrics_fields(postgres_db_real: PostgresDb, sample_sessions_for_component_metrics):
    """Ensure get_component_metrics returns only the fields asked for"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)

    metrics, _ = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=past_day, fields=["total_duration_ms", "max_duration_ms"]
    )
    assert metrics == [{"date": past_day, "total_duration_ms": 10000, "max_duration_ms": 4000}]

    metrics, _ = postgres_db_real.get_component_metrics(
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

    metrics, _ = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=past_day, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [{"date": past_day, "sessions_count": 4, "root_runs_count": 5}]

    with pytest.raises(ValueError):
        postgres_db_real.get_component_metrics(starting_date=past_day, ending_date=past_day, fields=["users_count"])


def test_get_component_metrics_never_calculates_rows(
    postgres_db_real: PostgresDb, sample_sessions_for_component_metrics
):
    """Ensure get_component_metrics reads only the rows calculate_metrics built"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)

    past_day = _utc_date(2)
    today = _utc_date(0)
    assert postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    ) == ([], None)
    assert _stored_rows(postgres_db_real) == {}

    postgres_db_real.calculate_metrics()
    metrics, latest_updated_at = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    )

    assert latest_updated_at is not None
    assert metrics == [
        {"date": past_day, "sessions_count": 4},
        {"date": _utc_date(1), "sessions_count": 0},
        {"date": today, "sessions_count": 1},
    ]
    assert len(_stored_rows(postgres_db_real)) == len(PAST_DAY_ROW_KEYS) + 1


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


def test_get_component_metrics_reads_one_owner_from_their_own_aggregate_metrics_row(
    postgres_db_real: PostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a read equals the sum of the rows, with every owner read from the everyone rows, one owner from their own
    aggregate metrics row, and the runs with no user from their component rows"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    today = _utc_date(0)
    days = [past_day, _utc_date(1), today]
    stored_rows = list(_stored_rows(postgres_db_real).values())
    fields = resolve_metrics_fields(None)

    # Every owner, then one owner: the same totals as the rows add up to
    metrics, _ = postgres_db_real.get_component_metrics(starting_date=past_day, ending_date=today)
    assert metrics == [
        {"date": day, **_merged_totals([row for row in stored_rows if row["date"] == day], fields)} for day in days
    ]
    metrics, _ = postgres_db_real.get_component_metrics(starting_date=past_day, ending_date=today, user_id="bob")
    assert metrics == [
        {"date": past_day, **_merged_totals([row for row in stored_rows if row["user_id"] == "bob"], fields)}
    ]

    # Change the everyone row: only the read of every owner moves
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            aggregate_metrics_table.update()
            .where(aggregate_metrics_table.c.date == past_day, aggregate_metrics_table.c.user_id == "")
            .values(agent_sessions_count=1000, team_sessions_count=0, workflow_sessions_count=0)
        )
    assert _sessions_counts(postgres_db_real, past_day, None) == [1000]
    assert _sessions_counts(postgres_db_real, past_day, "alice") == [1]
    assert _sessions_counts(postgres_db_real, past_day, "bob") == [2]
    assert _sessions_counts(postgres_db_real, past_day, "") == [1]
    assert _sessions_counts(postgres_db_real, past_day, "carol") == []

    # Change every component row: every owner and one owner are still read from the aggregate metrics rows
    table = postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(table.update().values(sessions_count=50))
    metrics, _ = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, fields=["sessions_count"]
    )
    assert [day_totals["sessions_count"] for day_totals in metrics] == [1000, 0, 1]
    metrics, _ = postgres_db_real.get_component_metrics(
        starting_date=past_day, ending_date=today, user_id="bob", fields=["sessions_count"]
    )
    assert metrics == [
        {
            "date": past_day,
            "sessions_count": sum(row["sessions_count"] for row in stored_rows if row["user_id"] == "bob"),
        }
    ]


def test_calculate_metrics_writes_a_month_aggregate_metrics_row_for_a_completed_month(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure every month of a calculated day gets an aggregate metrics row, completed once its last day is"""
    for session in sample_multi_month_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    this_month = _month_start(0)
    # The month of yesterday gets its aggregate metrics row even without traffic
    month_aggregate_metrics_rows = {
        key[1]: row for key, row in _stored_aggregate_metrics_rows(postgres_db_real).items() if key[0] == "monthly"
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
    alice_totals, _ = postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), user_id="alice"
    )
    assert alice_totals["sessions_count"] == 2
    assert alice_totals["input_tokens"] == 120
    assert alice_totals["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2, "cost": None}
    ]
    # The runs with no user are read from their day rows
    unowned_totals, _ = postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), user_id=""
    )
    assert unowned_totals["sessions_count"] == 1
    assert _aggregate_metrics_sessions_count(month_aggregate_metrics_rows[second_month]) == 1


def test_calculate_metrics_rebuilds_the_month_of_a_reopened_day(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure a month without a month aggregate metrics row gets it back once a write reopens one of its days"""
    for session in sample_multi_month_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics", create_table_if_not_found=True)

    # The first month loses its month aggregate metrics rows
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            aggregate_metrics_table.delete().where(
                aggregate_metrics_table.c.aggregation_period == "monthly", aggregate_metrics_table.c.date == first_month
            )
        )

    # A new session of carol reopens the 15th
    _persist(postgres_db_real, _session_on(first_month + timedelta(days=14), "first_month_carol", "carol"))
    result = postgres_db_real.calculate_metrics()
    assert result is not None
    assert (first_month + timedelta(days=14), "carol") in {(row["date"], row["user_id"]) for row in result}
    assert (
        _aggregate_metrics_sessions_count(_stored_aggregate_metrics_rows(postgres_db_real)[("monthly", first_month)])
        == 5
    )


def test_get_metrics_totals(postgres_db_real: PostgresDb, sample_multi_month_sessions_for_component_metrics):
    """Ensure the totals of a date range equal its days' totals summed, for every owner or one"""
    for session in sample_multi_month_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

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
            totals, _ = postgres_db_real.get_metrics_totals(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            metrics, _ = postgres_db_real.get_component_metrics(
                starting_date=starting_date, ending_date=ending_date, user_id=user_id
            )
            by_provider = [{**day, "model_metrics": _models_by_provider(day["model_metrics"])} for day in metrics]
            assert totals == list_metrics_totals_models(merge_metrics_totals(by_provider, fields))

    totals, _ = postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=today, fields=["sessions_count", "root_runs_count"]
    )
    assert totals == {"sessions_count": 6, "root_runs_count": 6}
    totals, latest_updated_at = postgres_db_real.get_metrics_totals(
        starting_date=first_month, ending_date=today, user_id="carol", fields=["sessions_count", "model_metrics"]
    )
    assert totals == {"sessions_count": 0, "model_metrics": []}
    assert latest_updated_at is None


def test_get_metrics_totals_reads_a_whole_month_from_its_month_rows(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure a month inside the date range is read from its month rows, each owner from their aggregate metrics row"""
    for session in sample_multi_month_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    second_month = _month_start(2)
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            aggregate_metrics_table.update()
            .where(
                aggregate_metrics_table.c.aggregation_period == "monthly",
                aggregate_metrics_table.c.date == first_month,
                aggregate_metrics_table.c.user_id == "",
            )
            .values(agent_sessions_count=1000, team_sessions_count=0, workflow_sessions_count=0)
        )
        sess.execute(
            aggregate_metrics_table.update()
            .where(
                aggregate_metrics_table.c.aggregation_period == "monthly",
                aggregate_metrics_table.c.date == first_month,
                aggregate_metrics_table.c.user_id == "bob",
            )
            .values(agent_sessions_count=500, team_sessions_count=0, workflow_sessions_count=0)
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
    # The read of each day never uses a month row, and a day without traffic has no aggregate metrics row to read
    metrics, _ = postgres_db_real.get_component_metrics(
        starting_date=first_month, ending_date=second_month - timedelta(days=1), fields=["sessions_count"]
    )
    assert metrics == [
        {"date": first_month, "sessions_count": 2},
        {"date": first_month + timedelta(days=14), "sessions_count": 2},
    ]


def test_metrics_versions_move_only_for_the_day_that_changed(
    postgres_db_real: PostgresDb, sample_sessions_for_component_metrics
):
    """Ensure a rebuild that only deletes a day's row moves that day's version and no other, and rewrites its everyone
    row with the day's totals"""
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
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()
    versions = _day_versions(postgres_db_real, _utc_date(2), _utc_date(0))
    today_key = f"daily {_utc_date(0).isoformat()}"

    # Mark every stored row, so a rewrite shows as a fresh updated_at
    with postgres_db_real.Session() as sess, sess.begin():
        for table_type in ("component_metrics", "aggregate_metrics"):
            table = postgres_db_real._get_table(table_type, create_table_if_not_found=True)
            sess.execute(table.update().values(updated_at=1))

    # Bob's only session of today is gone: his row is deleted and none is written, and today's version still moves
    assert postgres_db_real.delete_session("bob_today_session") is True
    assert postgres_db_real.calculate_metrics() is not None
    assert _day_versions(postgres_db_real, _utc_date(2), _utc_date(0)) == {
        **versions,
        today_key: versions[today_key] + 1,
    }
    # Only the aggregate metrics rows inside the date range are returned
    assert _day_versions(postgres_db_real, _utc_date(1), _utc_date(1)) == {f"daily {_utc_date(1).isoformat()}": 1}

    # Today's aggregate metrics row is rewritten, so a read of the day reports the new time
    today = _utc_date(0)
    metrics, read_updated_at = postgres_db_real.get_component_metrics(
        starting_date=today, ending_date=today, fields=["sessions_count", "root_runs_count"]
    )
    assert metrics == [{"date": today, "sessions_count": 1, "root_runs_count": 1}]
    assert read_updated_at != 1
    aggregate_metrics_rows = _stored_aggregate_metrics_rows(postgres_db_real)
    assert read_updated_at == aggregate_metrics_rows[("daily", today)]["updated_at"]
    assert all(
        row["updated_at"] == 1 for key, row in aggregate_metrics_rows.items() if key[0] == "daily" and key[1] != today
    )


def test_calculate_metrics_counts_a_late_run_of_yesterday(postgres_db_real: PostgresDb):
    """Ensure a run started before midnight and stored after a rebuild of today is counted on yesterday"""
    _persist(postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    postgres_db_real.calculate_metrics()
    versions = _day_versions(postgres_db_real, _utc_date(1), _utc_date(0))
    yesterday_key = f"daily {_utc_date(1).isoformat()}"
    assert versions[yesterday_key] == 1
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(1))]["root_runs_count"] == 0

    # Started at 23:59 yesterday, stored now
    yesterday = _utc_date(1)
    late_created_at = int(
        datetime(yesterday.year, yesterday.month, yesterday.day, 23, 59, tzinfo=timezone.utc).timestamp()
    )
    _persist(postgres_db_real, _session_at(late_created_at, "bob_late", "bob"))
    assert postgres_db_real.calculate_metrics() is not None

    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", yesterday)]["root_runs_count"] == 1
    assert (yesterday, "bob", "agent", "agent-1") in _stored_rows(postgres_db_real)
    assert _day_versions(postgres_db_real, _utc_date(1), _utc_date(0)) == {
        **versions,
        yesterday_key: 2,
    }


def test_calculate_metrics_never_rebuilds_an_empty_or_completed_day(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a first calculation builds only the days with traffic besides yesterday and today, and a later rebuild
    leaves a completed day alone"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_3_days_ago", "alice"))
    _persist(postgres_db_real, _session_on(_utc_date(0), "alice_today", "alice"))
    postgres_db_real.calculate_metrics()

    aggregate_metrics_rows = _stored_aggregate_metrics_rows(postgres_db_real)
    assert ("daily", _utc_date(2)) not in aggregate_metrics_rows
    assert aggregate_metrics_rows[("daily", _utc_date(3))]["completed"] is True

    calculated_days = []

    def _calculate(date_to_process, *args):
        calculated_days.append(date_to_process)
        return calculate_date_component_metrics(date_to_process, *args)

    monkeypatch.setattr("agno.db.postgres.postgres.calculate_date_component_metrics", _calculate)
    # A new session today moves yesterday and today
    _persist(postgres_db_real, _session_on(_utc_date(0), "alice_today_2", "alice"))
    postgres_db_real.calculate_metrics()
    assert calculated_days == [_utc_date(1), _utc_date(0)]


def test_calculate_metrics_counts_a_remote_member_run_once(postgres_db_real: PostgresDb):
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
    _persist(postgres_db_real, team_session)
    _persist(postgres_db_real, remote_session)
    postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    stored_rows = _stored_rows(postgres_db_real)
    assert stored_rows[(past_day, "bob", "team", "team-1")]["input_tokens"] == 0
    assert stored_rows[(past_day, "bob", "agent", "remote-agent")]["input_tokens"] == 10
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", past_day)]["input_tokens"] == 10


def test_calculate_metrics_names_a_parent_run_of_the_day_before(postgres_db_real: PostgresDb):
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
    _persist(postgres_db_real, team_session)
    postgres_db_real.calculate_metrics()

    assert _stored_rows(postgres_db_real)[(_utc_date(2), "bob", "agent", "agent-2")]["parent_component_id"] == "team-1"


def test_calculate_metrics_stores_each_day_as_it_is_calculated(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a day that fails to calculate leaves the days before it stored, and the next rebuild writes the rest"""
    for days_ago in [3, 2, 1, 0]:
        _persist(postgres_db_real, _session_on(_utc_date(days_ago), f"alice_{days_ago}_days_ago", "alice"))

    def _fail_two_days_ago(date_to_process, *args):
        if date_to_process == _utc_date(2):
            raise RuntimeError("Two days ago cannot be calculated")
        return calculate_date_component_metrics(date_to_process, *args)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.postgres.calculate_date_component_metrics", _fail_two_days_ago)
        with pytest.raises(RuntimeError):
            postgres_db_real.calculate_metrics()
    assert {row_id[0] for row_id in _stored_rows(postgres_db_real)} == {_utc_date(3)}
    # The stored day reopened its month for the next calculation
    assert set(_stored_aggregate_metrics_rows(postgres_db_real)) == {
        ("daily", _utc_date(3)),
        ("monthly", _utc_date(3).replace(day=1)),
    }

    postgres_db_real.calculate_metrics()
    assert {row_id[0] for row_id in _stored_rows(postgres_db_real)} == {
        _utc_date(3),
        _utc_date(2),
        _utc_date(1),
        _utc_date(0),
    }


def test_calculate_metrics_counts_nested_runs_at_every_depth(postgres_db_real: PostgresDb):
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
        result = sess.execute(build_component_metrics_runs_query(runs_table, _noon_utc(2), _noon_utc(2) + 1))
        (run,) = result.fetchall()
    assert [(nested_run["depth"], nested_run["run_id"]) for nested_run in run.nested_runs] == [
        (1, "nested_member"),
        (1, "nested_inner_team"),
        (2, "nested_inner_member"),
    ]
    assert all("messages" not in nested_run for nested_run in run.nested_runs)
    assert [nested_run["call_durations"] for nested_run in run.nested_runs] == [[0.6], [0.5], [0.4]]

    postgres_db_real.calculate_metrics()

    # The nested runs are no runs of their own, so their tokens and calls are on the row of the team run
    row = _stored_rows(postgres_db_real)[(_utc_date(2), "alice", "team", "team-1")]
    assert (row["input_tokens"], row["output_tokens"], row["total_tokens"]) == (19, 9, 28)
    assert row["model_calls_count"] == 4
    assert row["total_model_call_ms"] == 2700
    assert row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 4}}}


def test_calculate_metrics_skips_a_refresh_with_nothing_new(postgres_db_real: PostgresDb):
    """Ensure a calculation skips the rebuild while no session or run changed, and rebuilds after one did"""
    _persist(postgres_db_real, _session_on(_utc_date(0), "skipped_session", "alice"))
    # Written a minute ago, so no write shares the current second
    with postgres_db_real.Session() as sess, sess.begin():
        for table_type in ["sessions", "runs"]:
            table = postgres_db_real._get_table(table_type)
            sess.execute(table.update().values(updated_at=int(time.time()) - 60))

    assert postgres_db_real.calculate_metrics()
    assert postgres_db_real.calculate_metrics_dates() == []
    # Nothing changed, so calculate_metrics returns today's metrics as they are
    assert [metric["date"] for metric in postgres_db_real.calculate_metrics()] == [_utc_date(0)]

    _persist(postgres_db_real, _session_on(_utc_date(0), "new_session", "alice"))
    assert postgres_db_real.calculate_metrics() is not None
    assert _sessions_counts(postgres_db_real, _utc_date(0), None) == [2]


def test_calculate_metrics_rebuilds_a_reopened_day(postgres_db_real: PostgresDb):
    """Ensure a run saved on a completed day reopens it, and the next calculation completes it again"""
    session = _session_on(_utc_date(5), "alice_5_days_ago", "alice")
    _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()
    day_key = ("daily", _utc_date(5))
    day_row = _stored_aggregate_metrics_rows(postgres_db_real)[day_key]
    assert day_row["completed"] is True

    postgres_db_real.upsert_run(
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
    reopened_row = _stored_aggregate_metrics_rows(postgres_db_real)[day_key]
    assert (reopened_row["completed"], reopened_row["version"]) == (False, day_row["version"] + 1)

    postgres_db_real.calculate_metrics()
    rebuilt_row = _stored_aggregate_metrics_rows(postgres_db_real)[day_key]
    assert (rebuilt_row["completed"], rebuilt_row["root_runs_count"]) == (True, 2)


def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a day reopened between the read of its version and its everyone row stays open for the next calculation"""
    _persist(postgres_db_real, _session_on(_utc_date(5), "alice_5_days_ago", "alice"))

    def _reopen_before_the_upsert(session, table, aggregate_metrics_row, read_version):
        if (aggregate_metrics_row["aggregation_period"], aggregate_metrics_row["date"]) == ("daily", _utc_date(5)):
            # Another connection, as a write committed while the day is rebuilt
            with postgres_db_real.db_engine.connect() as other, other.begin():
                reopen_metrics_day(session=other, table=table, day=aggregate_metrics_row["date"])
        upsert_aggregate_metrics_row(
            session=session, table=table, aggregate_metrics_row=aggregate_metrics_row, read_version=read_version
        )

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.postgres.upsert_aggregate_metrics_row", _reopen_before_the_upsert)
        postgres_db_real.calculate_metrics()
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(5))]["completed"] is False

    postgres_db_real.calculate_metrics()
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(5))]["completed"] is True


def test_get_metrics_reads_the_metrics_table_until_the_first_calculation_finished(
    postgres_db_real: PostgresDb, monkeypatch
):
    """Ensure get_metrics of a database AgentOS calculates never calculates, and reads the metrics table until the
    first calculation has finished"""
    postgres_db_real.stop_metrics_refresh_on_read()
    _persist(postgres_db_real, _session_on(_utc_date(2), "alice_2_days_ago", "alice"))
    metrics_table = postgres_db_real._get_table("metrics", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            metrics_table.insert().values(
                {
                    "id": "stored_metrics_row",
                    "date": _utc_date(2),
                    "aggregation_period": "daily",
                    "user_id": "alice",
                    **{column: 0 for column in AGGREGATE_METRICS_COUNT_COLUMNS},
                    "agent_sessions_count": 7,
                    "token_metrics": {},
                    "model_metrics": [],
                    "created_at": int(time.time()),
                    "completed": True,
                }
            )
        )

    def _calculate():
        raise AssertionError("get_metrics never calculates metrics")

    with monkeypatch.context() as patch:
        patch.setattr(postgres_db_real, "calculate_metrics", _calculate)
        metrics, _ = postgres_db_real.get_metrics()
    assert [(row["id"], row["agent_sessions_count"]) for row in metrics] == [("stored_metrics_row", 7)]

    postgres_db_real.calculate_metrics()
    metrics, _ = postgres_db_real.get_metrics()
    assert [(row["date"], row["user_id"], row["agent_sessions_count"]) for row in metrics] == [
        (_utc_date(2), "alice", 1)
    ]


def test_upsert_session_without_an_aggregate_metrics_table(postgres_db_real: PostgresDb):
    """Ensure a session and its run of a past day are saved before any aggregate metrics table exists"""
    db = PostgresDb(
        db_engine=postgres_db_real.db_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        aggregate_metrics_table="test_unbuilt_aggregate_metrics",
    )
    _persist(db, _session_on(_utc_date(5), "alice_5_days_ago", "alice"))

    assert db.get_session("alice_5_days_ago") is not None
    assert db.get_run("alice_5_days_ago_run") is not None
    assert db.table_exists("test_unbuilt_aggregate_metrics") is False


def test_calculate_metrics_keeps_an_everyone_row_and_a_row_per_user(
    postgres_db_real: PostgresDb, sample_sessions_for_component_metrics
):
    """Ensure each calculated day, yesterday without traffic included, has an everyone row with every run, a row per
    user, and no row for the runs with no user"""
    for session in sample_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    past_day = _utc_date(2)
    yesterday = _utc_date(1)
    today = _utc_date(0)
    aggregate_metrics_rows = _stored_aggregate_metrics_rows(postgres_db_real)
    assert {key for key in aggregate_metrics_rows if key[0] == "daily"} == {
        ("daily", past_day),
        ("daily", yesterday),
        ("daily", today),
    }

    day_row = aggregate_metrics_rows[("daily", past_day)]
    assert _aggregate_metrics_sessions_count(day_row) == 4
    assert day_row["root_runs_count"] == 5
    assert day_row["status_metrics"] == {COMPLETED: 5, ERROR: 1}
    assert (day_row["input_tokens"], day_row["output_tokens"], day_row["total_tokens"]) == (385, 185, 570)
    assert day_row["duration_runs_count"] == 4
    assert day_row["max_duration_ms"] == 4000
    assert day_row["duration_buckets"] == {"le_1000": 1, "le_2000": 1, "le_3000": 1, "le_4000": 1}
    assert day_row["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 6}}}
    assert day_row["completed"] is metrics_day_completed(past_day)
    assert day_row["version"] == 1

    # Yesterday has no traffic and is still open; today is open too
    yesterday_row = aggregate_metrics_rows[("daily", yesterday)]
    assert (
        _aggregate_metrics_sessions_count(yesterday_row),
        yesterday_row["root_runs_count"],
        yesterday_row["max_duration_ms"],
    ) == (
        0,
        0,
        None,
    )
    assert yesterday_row["completed"] is False
    assert _aggregate_metrics_sessions_count(aggregate_metrics_rows[("daily", today)]) == 1
    assert aggregate_metrics_rows[("daily", today)]["completed"] is False

    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics")
    with postgres_db_real.Session() as sess:
        rows = {
            row.user_id: row
            for row in sess.execute(
                select(aggregate_metrics_table).where(
                    aggregate_metrics_table.c.aggregation_period == "daily", aggregate_metrics_table.c.date == past_day
                )
            ).fetchall()
        }
    assert sorted(rows) == ["", "alice", "bob"]
    assert (rows[""].input_tokens, rows[""].users_count) == (385, 2)
    assert (rows["alice"].input_tokens, rows["alice"].users_count) == (110, 1)

    # Every user's rows, plus the runs with no user from their component rows
    metrics, _ = postgres_db_real.get_metrics(starting_date=past_day, ending_date=past_day)
    assert [(metric["user_id"], metric["token_metrics"]["input_tokens"]) for metric in metrics] == [
        (None, 5),
        ("alice", 110),
        ("bob", 270),
    ]
    metrics, _ = postgres_db_real.get_metrics(starting_date=past_day, ending_date=past_day, user_id="")
    assert [(metric["user_id"], metric["token_metrics"]["input_tokens"]) for metric in metrics] == [(None, 5)]
    # Every user in one row per day, read from the everyone row
    metrics, _ = postgres_db_real.get_metrics_by_date(starting_date=past_day, ending_date=past_day)
    assert [(metric["users_count"], metric["token_metrics"]["input_tokens"]) for metric in metrics] == [(2, 385)]
    # One version per day: the everyone row's
    assert list(_day_versions(postgres_db_real, past_day, past_day)) == [f"daily {past_day.isoformat()}"]


def test_session_save_reopens_the_day_the_session_is_stored_on(postgres_db_real: PostgresDb):
    """Ensure a save that moves a session to another component reopens the day it was created on, not today"""
    session = _session_on(_utc_date(5), "moved_session", "alice")
    _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(5))]["completed"] is True

    moved = AgentSession(session_id="moved_session", agent_id="agent-2", user_id="alice", created_at=int(time.time()))
    postgres_db_real.upsert_session(moved)

    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(5))]["completed"] is False


def test_calculate_metrics_takes_over_a_lock_that_went_stale(postgres_db_real: PostgresDb):
    """Ensure a metrics refresh whose process stopped before releasing it is taken over once its lock went stale"""
    _persist(postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))
    refreshes_table = postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "stopped_process") is not None
    assert postgres_db_real.get_metrics_refresh_status()["status"] == "running"
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(refreshes_table.update().values(locked_at=0))

    assert postgres_db_real.calculate_metrics()
    assert postgres_db_real.get_metrics_refresh_status()["status"] == "completed"


def test_calculate_metrics_records_a_failed_refresh(postgres_db_real: PostgresDb, monkeypatch):
    """Ensure a calculation that fails leaves its error on the metrics refresh, read as a failed refresh"""
    _persist(postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))

    def _fail(*args):
        raise RuntimeError("The day cannot be calculated\n[SQL: SELECT run_data FROM test_schema.test_sessions_runs]")

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.postgres.calculate_date_component_metrics", _fail)
        with pytest.raises(RuntimeError):
            postgres_db_real.calculate_metrics()

    # Only the first line is kept, never the statement
    status = postgres_db_real.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", "The day cannot be calculated")


def test_calculate_metrics_rebuild_from_records_a_failed_reopen_before_any_refresh(
    postgres_db_real: PostgresDb, monkeypatch
):
    """Ensure a rebuild whose reopen fails before any metrics refresh ran leaves its error on the metrics refresh"""
    _persist(postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))

    def _fail(**kwargs):
        raise RuntimeError("The days cannot be reopened")

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.postgres.postgres.reopen_metrics_days_from", _fail)
        with pytest.raises(RuntimeError):
            postgres_db_real.calculate_metrics(rebuild_from=_utc_date(2))

    status = postgres_db_real.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", "The days cannot be reopened")


def test_delete_session_keeps_its_closed_day_closed(postgres_db_real: PostgresDb):
    """Ensure a deleted session's usage stays on its closed day: the delete reopens nothing"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    day_row = _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]

    assert postgres_db_real.delete_session("alice_session") is True

    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))] == day_row


def test_calculate_date_metrics_writes_nothing_after_losing_the_lock(postgres_db_real: PostgresDb):
    """Ensure a calculation whose lock went stale writes nothing once another process took the refresh over"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    table = postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics", create_table_if_not_found=True)
    refreshes_table = postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "paused") is not None

    # The lock goes stale, and another process takes the refresh over
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(refreshes_table.update().values(locked_at=0))
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "taker") is not None

    calculated = postgres_db_real._calculate_date_metrics(
        table,
        aggregate_metrics_table,
        postgres_db_real._get_table("sessions"),
        postgres_db_real._get_table("runs"),
        _utc_date(3),
        [],
        {},
        refreshes_table,
        "paused",
    )
    assert calculated is False
    assert _stored_rows(postgres_db_real) == {}
    assert _stored_aggregate_metrics_rows(postgres_db_real) == {}


def test_calculate_month_metrics_writes_nothing_after_losing_the_lock(
    postgres_db_real: PostgresDb, sample_multi_month_sessions_for_component_metrics
):
    """Ensure a month's calculation whose lock went stale writes nothing once another process took the refresh over"""
    for session in sample_multi_month_sessions_for_component_metrics:
        _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    first_month = _month_start(3)
    table = postgres_db_real._get_table("component_metrics", create_table_if_not_found=True)
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics", create_table_if_not_found=True)
    refreshes_table = postgres_db_real._get_table("metrics_refreshes", create_table_if_not_found=True)
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            aggregate_metrics_table.delete().where(
                aggregate_metrics_table.c.aggregation_period == "monthly", aggregate_metrics_table.c.date == first_month
            )
        )
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "paused") is not None

    # The lock goes stale, and another process takes the refresh over
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(refreshes_table.update().values(locked_at=0))
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "taker") is not None

    calculated = postgres_db_real._calculate_month_metrics(
        table, aggregate_metrics_table, first_month, refreshes_table, "paused"
    )
    assert calculated is False
    assert ("monthly", first_month) not in _stored_aggregate_metrics_rows(postgres_db_real)


def test_upsert_session_of_a_closed_day_from_a_fresh_process_is_stored(postgres_db_real: PostgresDb):
    """Ensure saves that reopen a closed day are stored by a process that never looked the aggregate metrics table up"""
    _persist(postgres_db_real, _session_on(_utc_date(5), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    fresh_db = PostgresDb(db_engine=postgres_db_real.db_engine, db_schema="test_schema", session_table="test_sessions")

    bob_session = _session_on(_utc_date(5), "bob_session", "bob")
    _persist(fresh_db, bob_session)
    fresh_db.upsert_sessions([_session_on(_utc_date(5), f"carol_session_{i}", "carol") for i in range(3)])

    assert fresh_db.get_run(bob_session.runs[0].run_id) is not None
    assert len(fresh_db.get_sessions(session_type=SessionType.AGENT)) == 5
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(5))]["completed"] is False
    # Looked up once, then read from the table cache by every later save
    assert fresh_db._get_cached_table("aggregate_metrics", fresh_db.aggregate_metrics_table_name) is not None


def test_cancel_pending_run_reopens_its_day(postgres_db_real: PostgresDb):
    """Ensure cancelling a pending run of a closed day reopens the day, as every other run write does"""
    session = _session_on(_utc_date(3), "alice_session", "alice")
    session.runs[0].status = RunStatus.pending
    _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    assert postgres_db_real.cancel_pending_run(
        "alice_session_run", session_id="alice_session", reason="stopped", user_id="alice"
    )
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False


def test_reassign_session_owner_reopens_its_day(postgres_db_real: PostgresDb):
    """Ensure moving a session of a closed day to another owner reopens the day, and marks the session updated"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    reassigned_at = int(time.time())

    assert postgres_db_real.reassign_session_owner("alice_session", previous_user_id="alice", user_id="bob")
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False
    assert postgres_db_real.get_session("alice_session", SessionType.AGENT).updated_at >= reassigned_at


def test_session_compaction_change_reopens_its_day(postgres_db_real: PostgresDb):
    """Ensure a session write that changes its compaction metrics reopens its closed day, and one that keeps them does
    not"""
    session = _session_on(_utc_date(3), "alice_session", "alice")
    session.session_data = {"compaction_metrics": {"total_tokens": 724}}
    _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    postgres_db_real.upsert_session(session)
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is True

    session.session_data = {"compaction_metrics": {"total_tokens": 1000}}
    postgres_db_real.upsert_session(session)
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False


def test_insert_session_if_absent_reopens_its_day(postgres_db_real: PostgresDb):
    """Ensure a session of a closed day created by the queued run prepare reopens the day"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()

    assert postgres_db_real.insert_session_if_absent(_session_on(_utc_date(3), "bob_session", "bob"))
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False


def test_append_run_to_session_if_absent_reopens_its_day(postgres_db_real: PostgresDb):
    """Ensure a run of a closed day appended by the queued run prepare reopens the day"""
    session = _session_on(_utc_date(3), "alice_session", "alice")
    _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()

    run = session.runs[0].to_dict()
    run["run_id"] = "alice_session_second_run"
    assert postgres_db_real.append_run_to_session_if_absent("alice_session", run, user_id="alice")
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False


def test_upsert_sessions_past_query_parameter_limit(postgres_db_real: PostgresDb):
    """Ensure a bulk save of more sessions than a 65,535-parameter query can list stores every one"""
    created_at = int(time.time())
    sessions = [AgentSession(session_id=f"s_{i}", agent_id="agent-1", created_at=created_at) for i in range(65_536)]

    assert len(postgres_db_real.upsert_sessions(sessions, deserialize=False)) == 65_536


def test_upsert_session_reopens_a_day_a_write_could_not_reopen(postgres_db_real: PostgresDb):
    """Ensure a save of a closed day never fails when the day cannot be reopened, and the next write reopens the day
    once its aggregate metrics row can be written again"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    table_name = postgres_db_real.aggregate_metrics_table_name
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            text(
                "CREATE FUNCTION test_schema.refuse_aggregate_metrics_writes() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION 'refused'; END $$ LANGUAGE plpgsql"
            )
        )
        sess.execute(
            text(
                f"CREATE TRIGGER refuse_aggregate_metrics_writes BEFORE INSERT OR UPDATE ON test_schema.{table_name} "
                "FOR EACH ROW EXECUTE FUNCTION test_schema.refuse_aggregate_metrics_writes()"
            )
        )
    try:
        bob_session = _session_on(_utc_date(3), "bob_session", "bob")
        _persist(postgres_db_real, bob_session)
        assert postgres_db_real.get_run(bob_session.runs[0].run_id) is not None
        assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is True
    finally:
        with postgres_db_real.Session() as sess, sess.begin():
            sess.execute(text(f"DROP TRIGGER IF EXISTS refuse_aggregate_metrics_writes ON test_schema.{table_name}"))
            sess.execute(text("DROP FUNCTION IF EXISTS test_schema.refuse_aggregate_metrics_writes()"))

    # A write of today, which reopens no day of its own
    _persist(postgres_db_real, _session_on(_utc_date(0), "carol_session", "carol"))

    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False


def test_calculate_metrics_dates_releases_the_lock_when_stopped(postgres_db_real: PostgresDb):
    """Ensure a calculation stopped between days, as on shutdown, releases the metrics refresh instead of holding it"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))

    assert postgres_db_real.calculate_metrics_dates(should_stop=lambda: True) is None

    refresh_status = postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert postgres_db_real.calculate_metrics() is not None


def test_calculate_metrics_dates_stops_between_the_batches_of_a_day(postgres_db_real: PostgresDb):
    """Ensure a stop asked during a day stops it at its next batch, before the day is written"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    # Checked before the day, then between its batches
    checks = iter([False])

    assert postgres_db_real.calculate_metrics_dates(should_stop=lambda: next(checks, True)) is None

    assert ("daily", _utc_date(3)) not in _stored_aggregate_metrics_rows(postgres_db_real)
    refresh_status = postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["error"]) == ("failed", METRICS_STOPPED_ERROR)


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(postgres_db_real: PostgresDb):
    """Ensure rebuild_from recounts a closed day that no write reopened, and builds a day with a session but no everyone
    row, as one written without reopening its day"""
    session = _session_on(_utc_date(3), "alice_session", "alice")
    _persist(postgres_db_real, session)
    postgres_db_real.calculate_metrics()
    # A delete reopens no day, so the closed day keeps the run
    postgres_db_real.delete_run(session.runs[0].run_id)
    sessions_table = postgres_db_real._get_table("sessions")
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            sessions_table.insert().values(
                session_id="unbuilt_session",
                session_type="agent",
                agent_id="agent-1",
                user_id="alice",
                created_at=_noon_utc(15),
            )
        )
    postgres_db_real.calculate_metrics()
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["root_runs_count"] == 1
    assert ("daily", _utc_date(15)) not in _stored_aggregate_metrics_rows(postgres_db_real)

    postgres_db_real.calculate_metrics(rebuild_from=_utc_date(20))

    day_row = _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]
    assert (day_row["root_runs_count"], day_row["completed"]) == (0, True)
    assert (
        _aggregate_metrics_sessions_count(_stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(15))])
        == 1
    )


def test_calculate_metrics_dates_stopped_after_a_completed_one_reads_completed(postgres_db_real: PostgresDb):
    """Ensure a calculation stopped between days after one that completed, as on a deploy, keeps reading the last
    completed refresh, and leaves the days it did not reach open"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    finished_at = postgres_db_real.get_metrics_refresh_status()["finished_at"]
    # A new session reopens a closed day
    _persist(postgres_db_real, _session_on(_utc_date(4), "bob_session", "bob"))

    assert postgres_db_real.calculate_metrics_dates(should_stop=lambda: True) is None

    refresh_status = postgres_db_real.get_metrics_refresh_status()
    assert (refresh_status["status"], refresh_status["finished_at"], refresh_status["error"]) == (
        "completed",
        finished_at,
        None,
    )
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(4))]["completed"] is False


def test_calculate_metrics_rebuilds_a_month_a_stopped_calculation_left(postgres_db_real: PostgresDb):
    """Ensure a calculation that stopped after a day of a past month leaves the month open, read from its days, and the
    next calculation totals it from its days"""
    last_month_day = _month_start(0) - timedelta(days=1)
    _persist(postgres_db_real, _session_on(last_month_day, "last_month_session", "alice"))
    _persist(postgres_db_real, _session_on(_utc_date(0), "today_session", "alice"))
    # Checked before the day and between its batches
    checks = iter([False, False])

    assert postgres_db_real.calculate_metrics_dates(should_stop=lambda: next(checks, True)) is None
    totals, _ = postgres_db_real.get_metrics_totals(
        starting_date=last_month_day.replace(day=1), ending_date=last_month_day, fields=["total_tokens"]
    )
    assert totals["total_tokens"] == 15
    postgres_db_real.calculate_metrics()

    aggregate_metrics_rows = _stored_aggregate_metrics_rows(postgres_db_real)
    month_row = aggregate_metrics_rows[("monthly", last_month_day.replace(day=1))]
    day_row = aggregate_metrics_rows[("daily", last_month_day)]
    assert (_aggregate_metrics_sessions_count(month_row), month_row["total_tokens"]) == (1, day_row["total_tokens"])
    assert day_row["total_tokens"] == 15


def test_calculate_metrics_rebuild_from_reopens_the_days_while_another_process_calculates(
    postgres_db_real: PostgresDb,
):
    """Ensure rebuild_from reopens its days even when another process holds the metrics refresh, so the next
    calculation rebuilds them"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    refreshes_table = postgres_db_real._get_table("metrics_refreshes")
    assert postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process") is not None

    assert postgres_db_real.calculate_metrics(rebuild_from=_utc_date(3)) is None
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is False

    postgres_db_real._release_metrics_refresh(refreshes_table, "other_process", stopped=True)
    postgres_db_real.calculate_metrics()
    assert _stored_aggregate_metrics_rows(postgres_db_real)[("daily", _utc_date(3))]["completed"] is True


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_completes(
    postgres_db_real: PostgresDb,
):
    """Ensure rebuild_from leaves yesterday and today to the next calculation when another process holds the metrics
    refresh and completes it with the fingerprint it read before the rebuild"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    refreshes_table = postgres_db_real._get_table("metrics_refreshes")
    refresh_row = postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process")
    assert refresh_row is not None

    assert postgres_db_real.calculate_metrics(rebuild_from=_utc_date(3)) is None

    postgres_db_real._release_metrics_refresh(
        refreshes_table,
        "other_process",
        fingerprint=refresh_row["fingerprint"],
        claimed_fingerprint=refresh_row["fingerprint"],
    )
    assert postgres_db_real.calculate_metrics_dates() == [_utc_date(3), _utc_date(1), _utc_date(0)]
    assert postgres_db_real.calculate_metrics_dates() == []


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_claimed_no_fingerprint(
    postgres_db_real: PostgresDb,
):
    """Ensure rebuild_from leaves yesterday and today to the next calculation when another process claimed the metrics
    refresh without a fingerprint and completes it"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    refreshes_table = postgres_db_real._get_table("metrics_refreshes")
    with postgres_db_real.Session() as sess, sess.begin():
        fingerprint = sess.execute(select(refreshes_table.c.fingerprint)).scalar_one()
        sess.execute(refreshes_table.update().values(fingerprint=null()))
    refresh_row = postgres_db_real._claim_metrics_refresh(refreshes_table, "other_process")
    assert refresh_row is not None and refresh_row["fingerprint"] is None

    assert postgres_db_real.calculate_metrics(rebuild_from=_utc_date(3)) is None

    postgres_db_real._release_metrics_refresh(
        refreshes_table, "other_process", fingerprint=fingerprint, claimed_fingerprint=refresh_row["fingerprint"]
    )
    assert postgres_db_real.calculate_metrics_dates() == [_utc_date(3), _utc_date(1), _utc_date(0)]
    assert postgres_db_real.calculate_metrics_dates() == []


def test_get_metrics_runs_a_first_calculation_without_deprecated_rows(postgres_db_real: PostgresDb):
    """Ensure a read runs the first calculation when the deprecated metrics table has no rows, and refreshes after"""
    _persist(postgres_db_real, _session_on(_utc_date(2), "alice_session", "alice"))

    metrics, _ = postgres_db_real.get_metrics()
    assert [(row["date"], row["user_id"]) for row in metrics] == [(_utc_date(2), "alice")]
    assert postgres_db_real.get_metrics_refresh_status()["status"] == "completed"

    _persist(postgres_db_real, _session_on(_utc_date(0), "bob_session", "bob"))
    # The last refresh on read was a minute ago
    postgres_db_real._metrics_refreshed_at = 0.0
    metrics, _ = postgres_db_real.get_metrics()
    assert [(row["date"], row["user_id"]) for row in metrics] == [(_utc_date(2), "alice"), (_utc_date(0), "bob")]


def test_get_metrics_returns_the_latest_update_of_every_day(postgres_db_real: PostgresDb):
    """Ensure the latest updated_at a read returns is of every day of the owner, as agno_metrics returned it, not
    only of the date range read"""
    _persist(postgres_db_real, _session_on(_utc_date(3), "alice_old_session", "alice"))
    _persist(postgres_db_real, _session_on(_utc_date(0), "alice_session", "alice"))
    postgres_db_real.calculate_metrics()
    aggregate_metrics_table = postgres_db_real._get_table("aggregate_metrics")
    later = int(time.time()) + 100
    with postgres_db_real.Session() as sess, sess.begin():
        sess.execute(
            aggregate_metrics_table.update()
            .where(
                aggregate_metrics_table.c.aggregation_period == "daily",
                aggregate_metrics_table.c.date == _utc_date(0),
                aggregate_metrics_table.c.user_id == "alice",
            )
            .values(updated_at=later)
        )

    metrics, latest_updated_at = postgres_db_real.get_metrics(
        starting_date=_utc_date(3), ending_date=_utc_date(3), user_id="alice"
    )
    assert [row["date"] for row in metrics] == [_utc_date(3)]
    assert latest_updated_at == later


def test_component_metrics_tables_for_a_long_session_table(postgres_db_real: PostgresDb):
    """Ensure a session table name long enough to push the component metrics table and index names past 63
    characters still builds the metrics tables"""
    long_db = PostgresDb(
        db_engine=postgres_db_real.db_engine,
        db_schema="test_schema",
        session_table="metrics_sessions_with_a_name_of_46_characters_",
        runs_table="long_name_runs",
    )
    try:
        _persist(long_db, _session_on(_utc_date(2), "alice_session", "alice"))
        assert long_db.calculate_metrics() is not None
        assert _stored_aggregate_metrics_rows(long_db)[("daily", _utc_date(2))]["agent_runs_count"] == 1
    finally:
        for table_type in ["component_metrics", "aggregate_metrics", "metrics_refreshes", "runs", "sessions"]:
            table = long_db._get_table(table_type)
            if table is not None:
                table.drop(long_db.db_engine)
