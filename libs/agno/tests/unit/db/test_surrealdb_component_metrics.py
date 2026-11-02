"""Unit tests for the component metrics methods of the SurrealDb class.

They run on SurrealDB's in-process engine, or on a server when SURREALDB_TEST_URL is set (with root/root
credentials), such as ws://localhost:8000.
"""

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import pytest

surrealdb = pytest.importorskip("surrealdb")

from agno.db.surrealdb import SurrealDb  # noqa: E402
from agno.db.surrealdb.metrics import desurrealize_metrics_row, reopen_metrics_day  # noqa: E402
from agno.db.utils import METRICS_REFRESH_ID, METRICS_STOPPED_ERROR  # noqa: E402
from agno.metrics import ModelMetrics, RunMetrics  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.run.team import TeamRunOutput  # noqa: E402
from agno.run.workflow import WorkflowRunOutput  # noqa: E402
from agno.session import AgentSession, TeamSession, WorkflowSession  # noqa: E402

RecordID = surrealdb.RecordID

COMPLETED = RunStatus.completed.value


@pytest.fixture
def surreal_db() -> SurrealDb:
    """Create a SurrealDb on its own database of the in-process engine, or of the server SURREALDB_TEST_URL names"""
    url = os.getenv("SURREALDB_TEST_URL", "mem://")
    client = surrealdb.Surreal(url)
    if url != "mem://":
        client.signin({"username": "root", "password": "root"})
    database = f"test_{uuid4().hex}"
    client.use("test", database)
    return SurrealDb(client, url, {}, "test", database, session_table="test_sessions", runs_table="test_runs")


def utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def noon_utc(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def run_metrics(input_tokens: int, cache_read_tokens: int = 0) -> RunMetrics:
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=10,
        total_tokens=input_tokens + 10,
        cache_read_tokens=cache_read_tokens,
        duration=1.5,
        details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI")]},
    )


def agent_run(run_id: str, created_at: int, input_tokens: int, status=RunStatus.completed, **kwargs) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id=kwargs.pop("agent_id", "agent-1"),
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=run_metrics(input_tokens, kwargs.pop("cache_read_tokens", 0)),
        created_at=created_at,
        **kwargs,
    )


def stored_rows(db: SurrealDb, table: str) -> List[Dict[str, Any]]:
    """Every stored row of the given metrics table, in the shape the rollup builds"""
    return [desurrealize_metrics_row(record) for record in db._query(f"SELECT * FROM {table}", {}, dict)]


def user_metrics_rows(db: SurrealDb) -> Dict[Tuple[str, date, str], Dict[str, Any]]:
    return {
        (row["aggregation_period"], row["date"], row["user_id"]): row
        for row in stored_rows(db, db.user_metrics_table_name)
    }


def everyone_row(db: SurrealDb, day: date, period: str = "daily") -> Dict[str, Any]:
    return user_metrics_rows(db)[(period, day, "")]


def build_dataset(db: SurrealDb) -> None:
    """Store an agent, a team with a member and a workflow, for two users and no user, over three days, with a paused
    run on the oldest day"""
    old_day, yesterday, today = utc_date(3), utc_date(1), utc_date(0)
    db.upsert_session(
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day))
    )
    db.upsert_run(agent_run("alice_run", noon_utc(old_day), 100, cache_read_tokens=7), "alice_session", "alice", 0)
    db.upsert_run(
        agent_run("alice_paused_run", noon_utc(old_day) + 60, 50, status=RunStatus.paused), "alice_session", "alice", 1
    )

    member_run = agent_run("member_run", noon_utc(yesterday) + 5, 20, agent_id="member-1", parent_run_id="team_run")
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=run_metrics(30, cache_read_tokens=3),
        member_responses=[member_run],
        created_at=noon_utc(yesterday),
    )
    db.upsert_session(
        TeamSession(session_id="bob_session", team_id="team-1", user_id="bob", created_at=noon_utc(yesterday))
    )
    db.upsert_run(team_run, session_id="bob_session", user_id="bob", run_index=0)
    db.upsert_run(member_run, session_id="bob_session", user_id="bob", run_index=1)

    db.upsert_session(
        WorkflowSession(session_id="workflow_session", workflow_id="workflow-1", created_at=noon_utc(today))
    )
    db.upsert_run(
        WorkflowRunOutput(
            run_id="workflow_run", workflow_id="workflow-1", status=RunStatus.completed, created_at=noon_utc(today)
        ),
        session_id="workflow_session",
        run_index=0,
    )


def ground_truth(db: SurrealDb) -> Dict[Tuple[date, str], Dict[str, int]]:
    """Count the stored sessions and runs directly: per day, everyone and each user"""
    truth: Dict[Tuple[date, str], Dict[str, int]] = {}

    def counts(day: date, user_id: Optional[str]) -> List[Dict[str, int]]:
        return [
            truth.setdefault(
                key,
                {
                    "agent_sessions_count": 0,
                    "team_sessions_count": 0,
                    "workflow_sessions_count": 0,
                    "agent_runs_count": 0,
                    "team_runs_count": 0,
                    "workflow_runs_count": 0,
                    "root_runs_count": 0,
                    "input_tokens": 0,
                    "cache_read_tokens": 0,
                },
            )
            for key in ([(day, ""), (day, user_id)] if user_id else [(day, "")])
        ]

    for session in db._query(f"SELECT * FROM {db.session_table_name}", {}, dict):
        session_type = "agent" if session.get("agent") else "team" if session.get("team") else "workflow"
        for day_counts in counts(session["created_at"].date(), session.get("user_id")):
            day_counts[f"{session_type}_sessions_count"] += 1
    for run in db._query(f"SELECT * FROM {db.runs_table_name}", {}, dict):
        metrics = run["run_data"].get("metrics") or {}
        for day_counts in counts(run["created_at"].date(), run.get("user_id")):
            day_counts[f"{run['run_type']}_runs_count"] += 1
            day_counts["root_runs_count"] += 0 if run.get("parent_run_id") else 1
            day_counts["input_tokens"] += metrics.get("input_tokens") or 0
            day_counts["cache_read_tokens"] += metrics.get("cache_read_tokens") or 0
    return truth


def assert_matches_ground_truth(db: SurrealDb) -> None:
    totals = user_metrics_rows(db)
    for (day, user_id), counts in ground_truth(db).items():
        row = totals[("daily", day, user_id)]
        assert {
            **{column: row[column] for column in counts if column != "cache_read_tokens"},
            "cache_read_tokens": row["token_details"].get("cache_read_tokens", 0),
        } == counts, (day, user_id)


def test_calculate_metrics_matches_a_direct_count_of_the_runs(surreal_db: SurrealDb):
    """Ensure every day's totals rows match a direct count of the stored runs"""
    build_dataset(surreal_db)

    calculated = surreal_db.calculate_metrics()

    old_day, yesterday, today = utc_date(3), utc_date(1), utc_date(0)
    assert calculated is not None
    assert {metric["date"] for metric in calculated} == {old_day, yesterday, today}
    assert_matches_ground_truth(surreal_db)
    totals = user_metrics_rows(surreal_db)
    assert (totals[("daily", yesterday, "")]["users_count"], totals[("daily", today, "")]["users_count"]) == (1, 0)
    assert totals[("daily", old_day, "")]["completed"] is True
    assert totals[("daily", yesterday, "")]["completed"] is False
    assert totals[("daily", old_day, "")]["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}
    assert totals[("daily", old_day, "")]["duration_runs_count"] == 1

    # The member run is counted under the team that started it
    rows = {
        (row["date"], row["user_id"], row["component_type"], row["component_id"]): row
        for row in stored_rows(surreal_db, surreal_db.component_metrics_table_name)
    }
    member_row = rows[(yesterday, "bob", "agent", "member-1")]
    assert (member_row["parent_component_id"], member_row["root_component_id"]) == ("team-1", "team-1")

    # The runs with no user are read from their component rows
    metrics, _ = surreal_db.get_metrics(starting_date=today, ending_date=today, user_id="")
    assert [(metric["user_id"], metric["workflow_runs_count"]) for metric in metrics] == [(None, 1)]
    metrics, latest_updated_at = surreal_db.get_metrics(starting_date=old_day, ending_date=today)
    assert latest_updated_at is not None
    assert sorted((metric["date"], metric["user_id"]) for metric in metrics) == [
        (old_day, "alice"),
        (yesterday, "bob"),
        (today, None),
    ]
    by_date, _ = surreal_db.get_metrics_by_date(starting_date=old_day, ending_date=today)
    assert [(metric["date"], metric["token_metrics"]["cache_read_tokens"]) for metric in by_date] == [
        # A first calculation builds only the days with data, and yesterday and today
        (old_day, 7),
        (yesterday, 3),
        (today, 0),
    ]
    assert (surreal_db.get_metrics_refresh_status() or {}).get("status") == "completed"


def test_get_component_metrics_and_totals(surreal_db: SurrealDb):
    """Ensure the component metrics and totals of a date range are read with the fields asked for"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day, today = utc_date(3), utc_date(0)

    metrics, latest_updated_at = surreal_db.get_component_metrics(
        old_day, today, fields=["sessions_count", "root_runs_count", "input_tokens", "cache_read_tokens"]
    )
    assert latest_updated_at is not None
    assert [(metric["date"], metric["root_runs_count"], metric["input_tokens"]) for metric in metrics] == [
        (old_day, 2, 150),
        (utc_date(1), 1, 50),
        (today, 1, 0),
    ]
    metrics, _ = surreal_db.get_component_metrics(old_day, today, user_id="bob", fields=["root_runs_count"])
    assert metrics == [{"date": utc_date(1), "root_runs_count": 1}]

    totals, _ = surreal_db.get_metrics_totals(old_day, today, fields=["sessions_count", "model_metrics"])
    assert totals == {
        "sessions_count": 3,
        "model_metrics": [{"model_id": "gpt-5", "model_provider": "OpenAI", "count": 4, "cost": None}],
    }
    totals, _ = surreal_db.get_metrics_totals(old_day, today, user_id="", fields=["root_runs_count"])
    assert totals == {"root_runs_count": 1}


def test_a_run_save_reopens_its_closed_day(surreal_db: SurrealDb):
    """Ensure saving a run of a closed day reopens it, and the next calculation completes it again"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(surreal_db, old_day)["version"]

    # The paused run completes; its continuation is saved with a later created_at, which the stored one wins over
    resumed_run = agent_run("alice_paused_run", noon_utc(utc_date(0)), 50)
    surreal_db.upsert_run(resumed_run, session_id="alice_session", user_id="alice")
    reopened_row = everyone_row(surreal_db, old_day)
    assert (reopened_row["completed"], reopened_row["version"]) == (False, version + 1)

    calculated = surreal_db.calculate_metrics()
    assert calculated is not None and old_day in {metric["date"] for metric in calculated}
    row = everyone_row(surreal_db, old_day)
    assert row["completed"] is True
    assert row["status_metrics"] == {COMPLETED: 2}
    assert_matches_ground_truth(surreal_db)


def test_a_new_session_on_a_closed_day_reopens_it(surreal_db: SurrealDb):
    """Ensure a new session on a closed day reopens it, while saving the same session again does not"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(surreal_db, old_day)["version"]

    # Saving the same session again changes nothing it is counted under
    surreal_db.upsert_session(
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day))
    )
    assert everyone_row(surreal_db, old_day)["version"] == version

    surreal_db.upsert_sessions(
        [AgentSession(session_id="late_session", agent_id="agent-1", user_id="carol", created_at=noon_utc(old_day))]
    )
    row = everyone_row(surreal_db, old_day)
    assert (row["completed"], row["version"]) == (False, version + 1)


def test_a_delete_does_not_reopen_its_day(surreal_db: SurrealDb):
    """Ensure deleting a session keeps its closed day closed"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)
    row = everyone_row(surreal_db, old_day)

    surreal_db.delete_session("alice_session")
    surreal_db.delete_runs(["alice_run"])
    surreal_db.calculate_metrics()

    # The deleted usage is kept until the day is rebuilt for another reason
    assert everyone_row(surreal_db, old_day) == row


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(surreal_db: SurrealDb):
    """Ensure rebuild_from rebuilds every day from it, deleting the stale rows of a day left with no data"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(surreal_db, old_day)["version"]
    surreal_db.delete_session("alice_session")
    surreal_db.delete_runs(["alice_run", "alice_paused_run"])

    calculated_dates = surreal_db.calculate_metrics_dates(rebuild_from=old_day)

    assert calculated_dates is not None and set(calculated_dates) >= {old_day, utc_date(1), utc_date(0)}
    row = everyone_row(surreal_db, old_day)
    assert (row["agent_runs_count"], row["agent_sessions_count"], row["completed"]) == (0, 0, True)
    assert row["version"] > version
    # The stale component rows of the rebuilt day are deleted
    assert not [
        row for row in stored_rows(surreal_db, surreal_db.component_metrics_table_name) if row["date"] == old_day
    ]
    assert_matches_ground_truth(surreal_db)
    # A day left with an everyone row of zeros is not returned
    metrics, _ = surreal_db.get_metrics_by_date(starting_date=old_day, ending_date=utc_date(0))
    assert old_day not in {metric["date"] for metric in metrics}
    metrics, _ = surreal_db.get_metrics(starting_date=old_day, ending_date=old_day)
    assert metrics == []


def test_rebuild_from_picks_every_day_with_data(surreal_db: SurrealDb):
    """Ensure rebuild_from picks every day with a session or a run, including a day no write reopened"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    # A run on a day no calculation built, written past the reopen
    late_day = utc_date(10)
    surreal_db._query(
        "CREATE $record CONTENT $content",
        {
            "record": RecordID(surreal_db.runs_table_name, "late_run"),
            "content": {
                **agent_run("late_run", noon_utc(late_day), 5).to_dict(),
                "run_type": "agent",
                "session_id": "alice_session",
                "created_at": datetime.fromtimestamp(noon_utc(late_day), tz=timezone.utc),
            },
        },
        dict,
    )
    assert late_day not in (surreal_db.calculate_metrics_dates() or [])

    calculated_dates = surreal_db.calculate_metrics_dates(rebuild_from=late_day)

    assert calculated_dates is not None and late_day in calculated_dates
    assert everyone_row(surreal_db, late_day)["agent_runs_count"] == 1


def test_calculate_metrics_returns_none_while_another_worker_holds_the_refresh(surreal_db: SurrealDb):
    """Ensure a calculation returns None while another worker holds the refresh"""
    build_dataset(surreal_db)
    refreshes_table = surreal_db._get_table("metrics_refreshes")
    assert surreal_db._claim_metrics_refresh(refreshes_table, "another-worker") is not None

    assert surreal_db.calculate_metrics() is None
    assert not surreal_db.table_exists(surreal_db.user_metrics_table_name) or user_metrics_rows(surreal_db) == {}
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["finished_at"]) == ("running", None)

    surreal_db._release_metrics_refresh(refreshes_table, "another-worker", error="it failed")
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["error"], status["finished_at"]) == (
        "failed",
        "it failed",
        None,
    )
    assert surreal_db.calculate_metrics()
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and status["status"] == "completed" and status["error"] is None
    assert status["finished_at"] is not None and status["finished_at"] >= status["started_at"]


def test_calculate_metrics_takes_over_a_stale_lock(surreal_db: SurrealDb):
    """Ensure a stale refresh reads as failed and the next calculation takes it over"""
    build_dataset(surreal_db)
    refreshes_table = surreal_db._get_table("metrics_refreshes")
    surreal_db._claim_metrics_refresh(refreshes_table, "stopped-worker")
    # A refresh still running a heartbeat ago is not taken over
    assert surreal_db.calculate_metrics() is None
    surreal_db._query(
        "UPDATE $refresh SET locked_at = time::unix(time::now()) - 301",
        {"refresh": RecordID(refreshes_table, METRICS_REFRESH_ID)},
        dict,
    )
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)

    assert surreal_db.calculate_metrics()
    assert (surreal_db.get_metrics_refresh_status() or {}).get("status") == "completed"
    refresh_row, _ = surreal_db._get_metrics_refresh_row(refreshes_table)
    assert refresh_row is not None and (refresh_row["locked_by"], refresh_row["locked_at"]) == (None, None)


def test_a_day_written_after_another_worker_took_the_refresh_over_is_not_written(surreal_db: SurrealDb):
    """Ensure a calculation whose refresh another worker took over writes no more days"""
    build_dataset(surreal_db)
    user_metrics_table = surreal_db._get_table("user_metrics")
    table = surreal_db._get_table("component_metrics")
    refreshes_table = surreal_db._get_table("metrics_refreshes")
    assert surreal_db._claim_metrics_refresh(refreshes_table, "this-worker") is not None
    surreal_db._release_metrics_refresh(refreshes_table, "this-worker")
    assert surreal_db._claim_metrics_refresh(refreshes_table, "another-worker") is not None

    assert not surreal_db._heartbeat_metrics_refresh(refreshes_table, "this-worker")
    assert not surreal_db._calculate_date_metrics(
        table,
        user_metrics_table,
        surreal_db.session_table_name,
        surreal_db.runs_table_name,
        utc_date(3),
        [],
        {},
        refreshes_table,
        "this-worker",
    )
    assert user_metrics_rows(surreal_db) == {}
    assert stored_rows(surreal_db, table) == []
    assert surreal_db._heartbeat_metrics_refresh(refreshes_table, "another-worker")


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_field(surreal_db: SurrealDb):
    """Ensure a run not yet migrated out of the session's legacy runs field is counted once, on its own day"""
    old_day = utc_date(3)
    stored_run = agent_run("stored_run", noon_utc(old_day), 10)
    legacy_only_run = agent_run("legacy_only_run", noon_utc(old_day), 30)
    surreal_db.upsert_session(
        AgentSession(session_id="legacy_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day))
    )
    surreal_db.upsert_run(stored_run, session_id="legacy_session", user_id="alice", run_index=0)
    surreal_db._query(
        "UPDATE $record SET runs = $runs",
        {
            "record": RecordID("test_sessions", "legacy_session"),
            "runs": [stored_run.to_dict(), legacy_only_run.to_dict()],
        },
        dict,
    )

    surreal_db.calculate_metrics()

    row = everyone_row(surreal_db, old_day)
    assert (row["agent_sessions_count"], row["agent_runs_count"], row["input_tokens"]) == (1, 2, 40)


def test_calculate_metrics_builds_the_day_of_a_legacy_run_alone_on_its_day(surreal_db: SurrealDb):
    """Ensure a legacy run dated on a day that holds no session or run of the tables is built on its own day"""
    session_day, legacy_day = utc_date(5), utc_date(4)
    surreal_db.upsert_session(
        AgentSession(session_id="legacy_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(session_day))
    )
    surreal_db._query(
        "UPDATE $record SET runs = $runs",
        {
            "record": RecordID("test_sessions", "legacy_session"),
            "runs": [agent_run("legacy_run", noon_utc(legacy_day), 30).to_dict()],
        },
        dict,
    )

    calculated_dates = surreal_db.calculate_metrics_dates()

    assert calculated_dates is not None and legacy_day in calculated_dates
    row = everyone_row(surreal_db, legacy_day)
    assert (row["agent_runs_count"], row["input_tokens"]) == (1, 30)
    assert everyone_row(surreal_db, session_day)["agent_sessions_count"] == 1


def test_a_read_never_calculates_metrics(surreal_db: SurrealDb):
    """Ensure a read calculates no metrics before a first calculation has finished"""
    build_dataset(surreal_db)

    assert surreal_db.get_metrics() == ([], None)
    assert surreal_db.get_metrics_by_date() == ([], None)
    assert not surreal_db.table_exists(surreal_db.metrics_refreshes_table_name)


def test_calculate_metrics_skips_a_refresh_with_nothing_new(surreal_db: SurrealDb):
    """Ensure a calculation skips the rebuild while no session or run changed, and returns today"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()

    # Yesterday and today are rebuilt while their runs were written in the current second, then left as they are
    surreal_db.calculate_metrics()
    time.sleep(1.1)
    surreal_db.calculate_metrics()
    versions = {key: row["version"] for key, row in user_metrics_rows(surreal_db).items()}
    assert surreal_db.calculate_metrics_dates() == []
    # Nothing changed: today's metrics come back
    assert [(metric["date"], metric["user_id"]) for metric in surreal_db.calculate_metrics() or []] == [
        (utc_date(0), None)
    ]
    assert {key: row["version"] for key, row in user_metrics_rows(surreal_db).items()} == versions


def test_get_metrics_reads_the_metrics_table_until_the_first_calculation_finished(surreal_db: SurrealDb):
    """Ensure a read before a first calculation reads the deprecated table, without creating it"""
    assert surreal_db.get_metrics() == ([], None)
    # The deprecated table is never created by a read
    assert not surreal_db.table_exists(surreal_db.metrics_table_name)
    assert surreal_db.get_metrics_refresh_status() is None
    assert surreal_db.get_component_metrics(utc_date(1), utc_date(0)) == ([], None)


def test_completed_month_gets_month_rows(surreal_db: SurrealDb, monkeypatch):
    """Ensure a completed month gets its month totals rows"""
    monkeypatch.setattr("agno.db.surrealdb.surrealdb.METRICS_BATCH_SIZE", 1)
    old_day = utc_date(70)
    for user_id in ["alice", "bob"]:
        surreal_db.upsert_session(
            AgentSession(
                session_id=f"{user_id}_session", agent_id="agent-1", user_id=user_id, created_at=noon_utc(old_day)
            )
        )
        surreal_db.upsert_run(
            agent_run(f"{user_id}_run", noon_utc(old_day), 10), f"{user_id}_session", user_id, run_index=0
        )

    surreal_db.calculate_metrics()

    month_start = old_day.replace(day=1)
    month_row = everyone_row(surreal_db, month_start, "monthly")
    assert (month_row["agent_sessions_count"], month_row["users_count"], month_row["completed"]) == (2, 2, True)
    assert user_metrics_rows(surreal_db)[("monthly", month_start, "alice")]["agent_runs_count"] == 1
    # The component metrics table keeps day rows only
    assert {row["aggregation_period"] for row in stored_rows(surreal_db, surreal_db.component_metrics_table_name)} == {
        "daily"
    }
    totals, _ = surreal_db.get_metrics_totals(
        month_start, (month_start + timedelta(days=40)).replace(day=1) - timedelta(days=1), fields=["sessions_count"]
    )
    assert totals == {"sessions_count": 2}


def test_a_stopped_calculation_releases_the_refresh(surreal_db: SurrealDb):
    """Ensure a stopped calculation writes the days it calculated and releases the refresh"""
    build_dataset(surreal_db)

    # A first calculation that stopped has nothing to show
    assert surreal_db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)
    assert surreal_db.calculate_metrics()

    # A later one that stopped leaves the last completed refresh as it was
    surreal_db.upsert_run(agent_run("alice_run_3", noon_utc(utc_date(3)) + 120, 1), "alice_session", "alice", 2)
    assert surreal_db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["error"]) == ("completed", None)
    assert everyone_row(surreal_db, utc_date(3))["completed"] is False


def test_a_calculation_stopped_before_its_months_leaves_the_month_open(surreal_db: SurrealDb, monkeypatch):
    """Ensure a day rebuilt by a calculation that stopped before its months reopens its month, which the next
    calculation rebuilds, and a read of the open month totals its days"""
    old_day = utc_date(70)
    month_start = old_day.replace(day=1)
    month_end = (month_start + timedelta(days=40)).replace(day=1) - timedelta(days=1)
    surreal_db.upsert_session(
        AgentSession(session_id="old_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day))
    )
    surreal_db.upsert_run(agent_run("old_run", noon_utc(old_day), 10), "old_session", "alice", 0)
    surreal_db.calculate_metrics()
    assert everyone_row(surreal_db, month_start, "monthly")["input_tokens"] == 10

    surreal_db.upsert_run(agent_run("late_run", noon_utc(old_day) + 60, 5), "old_session", "alice", 1)
    # Stops once every day is built, before the months
    stopping = []
    get_open_metrics_months = SurrealDb._get_open_metrics_months

    def _stop_before_the_months(self, user_metrics_table):
        stopping.append(True)
        return get_open_metrics_months(self, user_metrics_table)

    with monkeypatch.context() as patch:
        patch.setattr(SurrealDb, "_get_open_metrics_months", _stop_before_the_months)
        assert surreal_db.calculate_metrics_dates(should_stop=lambda: bool(stopping)) is None
    month_row = everyone_row(surreal_db, month_start, "monthly")
    assert (month_row["completed"], month_row["input_tokens"]) == (False, 10)
    totals, _ = surreal_db.get_metrics_totals(month_start, month_end, fields=["input_tokens"])
    assert totals == {"input_tokens": 15}

    surreal_db.calculate_metrics()
    month_row = everyone_row(surreal_db, month_start, "monthly")
    assert (month_row["completed"], month_row["input_tokens"]) == (True, 15)


def test_a_run_save_before_any_calculation_creates_no_metrics_table(surreal_db: SurrealDb):
    """Ensure a run save before any calculation creates no metrics table"""
    surreal_db.upsert_session(
        AgentSession(session_id="old_session", agent_id="agent-1", created_at=noon_utc(utc_date(5)))
    )
    surreal_db.upsert_run(agent_run("old_run", noon_utc(utc_date(5)), 10), session_id="old_session", run_index=0)

    assert not surreal_db.table_exists(surreal_db.user_metrics_table_name)
    assert surreal_db._metrics_days_not_reopened == set()


@pytest.mark.parametrize("metrics_table", [None, "custom_metrics"])
def test_metrics_table_names(metrics_table):
    """Ensure the metrics table names follow the session table, with or without metrics_table"""
    db = SurrealDb(None, "mem://", {}, "test", "test", session_table="custom_sessions", metrics_table=metrics_table)
    assert (db.component_metrics_table_name, db.user_metrics_table_name) == (
        "custom_sessions_component_metrics",
        "custom_sessions_user_metrics",
    )
    assert db.metrics_table_name == (metrics_table or "agno_metrics")


def test_calculate_metrics_skips_fork_copies_and_reads_request_durations(surreal_db: SurrealDb):
    """Ensure a run copied into a forked session is not counted, and each request of a run is timed from its
    messages"""
    day = utc_date(2)
    timed_run = agent_run(
        "timed_run",
        noon_utc(day),
        10,
        messages=[
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi", metrics={"duration": 0.25}),
            Message(role="assistant", content="again", metrics={"duration": 0.5}, from_history=True),
        ],
    )
    copied_run = agent_run("copied_run", noon_utc(day), 40)
    copied_run.forked_from_session_id = "timed_session"
    for session_id, run in [("timed_session", timed_run), ("copied_session", copied_run)]:
        surreal_db.upsert_session(
            AgentSession(session_id=session_id, agent_id="agent-1", user_id="carol", created_at=noon_utc(day))
        )
        surreal_db.upsert_run(run, session_id=session_id, user_id="carol", run_index=0)

    surreal_db.calculate_metrics()

    row = everyone_row(surreal_db, day)
    assert (row["agent_runs_count"], row["input_tokens"]) == (1, 10)
    assert (row["model_calls_count"], row["total_model_call_ms"]) == (1, 250)


def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(surreal_db: SurrealDb, monkeypatch):
    """Ensure a day reopened between the read of its version and the write of its rows stays open for the next
    calculation"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)
    surreal_db.upsert_run(agent_run("alice_run_3", noon_utc(old_day) + 120, 1), "alice_session", "alice", 2)
    get_user_metrics_rows_to_write = SurrealDb._get_user_metrics_rows_to_write

    def _reopen_before_the_write(self, user_metrics_table, user_metrics_rows, rows_changed):
        # Another write, committed after the day's version was read and before its rows are written
        reopen_metrics_day(self.client, user_metrics_table, old_day)
        return get_user_metrics_rows_to_write(self, user_metrics_table, user_metrics_rows, rows_changed)

    with monkeypatch.context() as patch:
        patch.setattr(SurrealDb, "_get_user_metrics_rows_to_write", _reopen_before_the_write)
        surreal_db.calculate_metrics()
    assert everyone_row(surreal_db, old_day)["completed"] is False

    surreal_db.calculate_metrics()
    assert everyone_row(surreal_db, old_day)["completed"] is True


def test_a_run_save_never_fails_because_of_metrics(surreal_db: SurrealDb, monkeypatch):
    """Ensure a save whose reopen fails is stored, and the day is reopened by the next write"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)

    def _refuse(client, table, day):
        raise RuntimeError("refused")

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.surrealdb.surrealdb.reopen_metrics_day", _refuse)
        surreal_db.upsert_run(agent_run("alice_run_3", noon_utc(old_day) + 120, 1), "alice_session", "alice", 2)
    assert surreal_db.get_run("alice_run_3") is not None
    assert surreal_db._metrics_days_not_reopened == {old_day}
    assert everyone_row(surreal_db, old_day)["completed"] is True

    surreal_db.upsert_run(agent_run("today_run", noon_utc(utc_date(0)), 1), "workflow_session", None, 1)
    assert surreal_db._metrics_days_not_reopened == set()
    assert everyone_row(surreal_db, old_day)["completed"] is False


def test_get_metrics_versions_move_only_for_the_day_that_changed(surreal_db: SurrealDb):
    """Ensure no version is read before a first calculation, and only a changed day's version moves"""
    build_dataset(surreal_db)
    old_day = utc_date(3)
    assert surreal_db.get_metrics_versions(old_day, utc_date(0)) is None

    surreal_db.calculate_metrics()
    versions = surreal_db.get_metrics_versions(old_day, utc_date(0))
    assert versions is not None
    assert {key for key in versions if key.startswith("daily")} == {
        f"daily {utc_date(days_ago).isoformat()}" for days_ago in [3, 1, 0]
    }

    # A reopened day is rebuilt: its version moves, the other days' stay
    surreal_db.upsert_run(agent_run("alice_run_3", noon_utc(old_day) + 120, 1), "alice_session", "alice", 2)
    time.sleep(1.1)
    surreal_db.calculate_metrics()
    surreal_db.calculate_metrics()
    changed = surreal_db.get_metrics_versions(old_day, utc_date(0))
    assert changed is not None
    assert changed[f"daily {old_day.isoformat()}"] > versions[f"daily {old_day.isoformat()}"]
    assert {key for key in versions if key.startswith("daily") and changed[key] != versions[key]} <= {
        f"daily {old_day.isoformat()}",
        f"daily {utc_date(1).isoformat()}",
        f"daily {utc_date(0).isoformat()}",
    }
