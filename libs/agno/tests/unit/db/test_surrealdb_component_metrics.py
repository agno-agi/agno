"""Unit tests for the component metrics methods of the SurrealDb class.

They run on SurrealDB's in-process engine, or on a server when SURREALDB_TEST_URL is set (with root/root
credentials), such as ws://localhost:8000.
"""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import pytest

surrealdb = pytest.importorskip("surrealdb")

from agno.db.migrations.manager import MigrationManager  # noqa: E402
from agno.db.surrealdb import SurrealDb  # noqa: E402
from agno.db.surrealdb.metrics import desurrealize_metrics_row  # noqa: E402
from agno.db.utils import METRICS_LOCK_SECONDS, METRICS_REFRESH_ID, METRICS_STOPPED_ERROR  # noqa: E402
from agno.metrics import ModelMetrics, RunMetrics, ToolCallMetrics  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.models.response import ToolExecution  # noqa: E402
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


def aggregate_metrics_rows(db: SurrealDb) -> Dict[Tuple[str, date, str], Dict[str, Any]]:
    return {
        (row["aggregation_period"], row["date"], row["user_id"]): row
        for row in stored_rows(db, db.aggregate_metrics_table_name)
    }


def everyone_row(db: SurrealDb, day: date, period: str = "daily") -> Dict[str, Any]:
    return aggregate_metrics_rows(db)[(period, day, "")]


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
    rows = aggregate_metrics_rows(db)
    for (day, user_id), counts in ground_truth(db).items():
        row = rows[("daily", day, user_id)]
        assert {
            **{column: row[column] for column in counts if column != "cache_read_tokens"},
            "cache_read_tokens": row["token_details"].get("cache_read_tokens", 0),
        } == counts, (day, user_id)


def test_calculate_metrics_matches_a_direct_count_of_the_runs(surreal_db: SurrealDb):
    """Ensure every day's aggregate metrics rows match a direct count of the stored runs"""
    build_dataset(surreal_db)

    calculated = surreal_db.calculate_metrics()

    old_day, yesterday, today = utc_date(3), utc_date(1), utc_date(0)
    assert calculated is not None
    assert {metric["date"] for metric in calculated} == {old_day, yesterday, today}
    assert_matches_ground_truth(surreal_db)
    aggregate_metrics = aggregate_metrics_rows(surreal_db)
    assert aggregate_metrics[("daily", yesterday, "")]["users_count"] == 1
    assert aggregate_metrics[("daily", today, "")]["users_count"] == 0
    assert aggregate_metrics[("daily", old_day, "")]["completed"] is True
    assert aggregate_metrics[("daily", yesterday, "")]["completed"] is False
    assert aggregate_metrics[("daily", old_day, "")]["model_metrics"] == {"OpenAI": {"gpt-5": {"count": 2}}}
    assert aggregate_metrics[("daily", old_day, "")]["duration_runs_count"] == 1

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


def test_calculate_metrics_takes_over_a_lock_that_went_stale(surreal_db: SurrealDb):
    """Ensure a stale refresh reads as failed and the next calculation takes it over"""
    build_dataset(surreal_db)
    refreshes_table = surreal_db._get_table("metrics_refreshes")
    surreal_db._claim_metrics_refresh(refreshes_table, "stopped-worker")
    # A refresh still running a heartbeat ago is not taken over
    assert surreal_db.calculate_metrics() is None
    surreal_db._query(
        f"UPDATE $refresh SET locked_at = time::unix(time::now()) - {METRICS_LOCK_SECONDS + 1}",
        {"refresh": RecordID(refreshes_table, METRICS_REFRESH_ID)},
        dict,
    )
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)

    assert surreal_db.calculate_metrics()
    assert (surreal_db.get_metrics_refresh_status() or {}).get("status") == "completed"
    refresh_row, _ = surreal_db._get_metrics_refresh_row(refreshes_table)
    assert refresh_row is not None and (refresh_row["locked_by"], refresh_row["locked_at"]) == (None, None)


def test_calculate_date_metrics_writes_nothing_after_losing_the_lock(surreal_db: SurrealDb):
    """Ensure a calculation whose refresh another worker took over writes no more days"""
    build_dataset(surreal_db)
    aggregate_metrics_table = surreal_db._get_table("aggregate_metrics")
    table = surreal_db._get_table("component_metrics")
    refreshes_table = surreal_db._get_table("metrics_refreshes")
    assert surreal_db._claim_metrics_refresh(refreshes_table, "this-worker") is not None
    surreal_db._release_metrics_refresh(refreshes_table, "this-worker")
    assert surreal_db._claim_metrics_refresh(refreshes_table, "another-worker") is not None

    assert not surreal_db._heartbeat_metrics_refresh(refreshes_table, "this-worker")
    assert not surreal_db._calculate_date_metrics(
        table,
        aggregate_metrics_table,
        surreal_db.session_table_name,
        surreal_db.runs_table_name,
        utc_date(3),
        [],
        {},
        refreshes_table,
        "this-worker",
    )
    assert aggregate_metrics_rows(surreal_db) == {}
    assert stored_rows(surreal_db, table) == []
    assert surreal_db._heartbeat_metrics_refresh(refreshes_table, "another-worker")


def test_a_day_write_returned_as_an_error_fails_the_refresh(surreal_db: SurrealDb, monkeypatch):
    """Ensure a day write that SDK 1.x returns as its error message fails the refresh, and the next one completes"""
    build_dataset(surreal_db)
    client = surreal_db.client
    query = client.query

    def _fail_day_write(statement, variables=None):
        if "IF $held" in statement:
            return "An error occurred: write failed"
        return query(statement, variables)

    with monkeypatch.context() as patch:
        patch.setattr(client, "query", _fail_day_write)
        with pytest.raises(RuntimeError, match="write failed"):
            surreal_db.calculate_metrics()
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and (status["status"], status["error"]) == ("failed", "An error occurred: write failed")

    assert surreal_db.calculate_metrics()
    status = surreal_db.get_metrics_refresh_status()
    assert status is not None and status["status"] == "completed"


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
    # Not yet migrated to v3.0.0, so the legacy runs are read
    surreal_db.upsert_schema_version(surreal_db.session_table_name, "2.5.0")

    surreal_db.calculate_metrics()

    row = everyone_row(surreal_db, old_day)
    assert (row["agent_sessions_count"], row["agent_runs_count"], row["input_tokens"]) == (1, 2, 40)


def test_the_legacy_runs_read_leaves_out_a_run_copied_into_a_forked_session(surreal_db: SurrealDb):
    """Ensure a legacy run a forked session copied is not read, as the runs table read leaves it out"""
    old_day = utc_date(3)
    legacy_run = agent_run("legacy_run", noon_utc(old_day), 30)
    copied_run = agent_run("copied_run", noon_utc(old_day), 30)
    copied_run.forked_from_session_id = "legacy_session"
    for session_id, run in [("legacy_session", legacy_run), ("forked_session", copied_run)]:
        surreal_db.upsert_session(
            AgentSession(session_id=session_id, agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day))
        )
        surreal_db._query(
            "UPDATE $record SET runs = $runs",
            {"record": RecordID("test_sessions", session_id), "runs": [run.to_dict()]},
            dict,
        )

    legacy_runs = surreal_db._get_metrics_legacy_runs(
        "test_sessions", None, datetime.fromtimestamp(0, tz=timezone.utc), datetime.now(timezone.utc)
    )

    assert [run["run_id"] for run in legacy_runs] == ["legacy_run"]


def test_calculate_metrics_counts_tool_calls(surreal_db: SurrealDb):
    """Ensure each tool call is counted under its tool, that a tool call a forked run copied is not, and that a totals
    read adds the tools up"""
    day = utc_date(2)
    copied_call = ToolExecution(
        tool_call_id="copied-call",
        tool_name="search",
        tool_args={"query": "agno"},
        metrics=ToolCallMetrics(duration=0.4),
    )
    new_call = ToolExecution(tool_call_id="new-call", tool_name="search", metrics=ToolCallMetrics(duration=0.1))
    surreal_db.upsert_session(
        AgentSession(session_id="fork_session", agent_id="agent-1", user_id="bob", created_at=noon_utc(day))
    )
    original = agent_run(
        "original_run",
        noon_utc(day),
        10,
        messages=[Message(role="tool", tool_call_id="copied-call", content="agno")],
        tools=[copied_call],
    )
    forked = agent_run(
        "forked_run",
        noon_utc(day) + 1,
        10,
        messages=[
            Message(role="tool", tool_call_id="copied-call", content="agno"),
            Message(role="tool", tool_call_id="new-call", content="agno"),
        ],
        tools=[copied_call, new_call],
        forked_from_message_index=1,
    )
    surreal_db.upsert_run(original, session_id="fork_session", user_id="bob", run_index=0)
    surreal_db.upsert_run(forked, session_id="fork_session", user_id="bob", run_index=1)

    surreal_db.calculate_metrics()

    # The forked run counts only the tool call it made
    expected = {
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
    metrics, _ = surreal_db.get_component_metrics(day, day, fields=["tool_metrics"])
    assert metrics[0]["tool_metrics"] == expected
    totals, _ = surreal_db.get_metrics_totals(day, day, user_id="bob", fields=["tool_metrics"])
    assert totals == {"tool_metrics": expected}


def test_get_metrics_returns_a_day_with_only_a_regenerated_run(surreal_db: SurrealDb):
    """Ensure a day whose only run was regenerated, with tokens but no count, is returned"""
    day = utc_date(3)
    surreal_db.upsert_session(
        AgentSession(session_id="carol_session", agent_id="agent-1", user_id="carol", created_at=noon_utc(utc_date(2)))
    )
    surreal_db.upsert_run(
        agent_run("regenerated_run", noon_utc(day), 20, status=RunStatus.regenerated),
        session_id="carol_session",
        user_id="carol",
    )

    surreal_db.calculate_metrics()

    metrics, _ = surreal_db.get_metrics(starting_date=day, ending_date=day, user_id="carol")
    assert [(row["date"], row["agent_runs_count"], row["token_metrics"]["total_tokens"]) for row in metrics] == [
        (day, 0, 30)
    ]


def test_calculate_metrics_dates_releases_the_lock_when_stopped(surreal_db: SurrealDb):
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


def test_a_created_sessions_table_reads_no_legacy_runs(surreal_db: SurrealDb, monkeypatch):
    """Ensure creating the sessions table stores the latest schema version, so a calculation reads no legacy runs"""
    surreal_db.upsert_session(
        AgentSession(session_id="new_session", agent_id="agent-1", created_at=noon_utc(utc_date(1)))
    )
    surreal_db.upsert_run(agent_run("new_run", noon_utc(utc_date(1)), 10), session_id="new_session", run_index=0)
    latest_schema_version = MigrationManager(surreal_db).latest_schema_version.public
    assert surreal_db.get_latest_schema_version(surreal_db.session_table_name) == latest_schema_version

    def _fail_legacy_runs_read(*args, **kwargs):
        raise AssertionError("legacy runs were read")

    monkeypatch.setattr(surreal_db, "_get_metrics_legacy_runs", _fail_legacy_runs_read)
    assert surreal_db.calculate_metrics()


def test_an_unstamped_sessions_table_with_no_legacy_runs_is_read_for_them_once(surreal_db: SurrealDb, monkeypatch):
    """Ensure a sessions table stamped with no version, as 3.0 and 3.1 left it, is read for legacy runs once, and not
    again once that read of every session found none"""
    surreal_db.upsert_session(AgentSession(session_id="s1", agent_id="agent-1", created_at=noon_utc(utc_date(1))))
    monkeypatch.setattr(surreal_db, "get_latest_schema_version", lambda table_name="": "2.0.0")
    legacy_reads: List[Any] = []
    monkeypatch.setattr(surreal_db, "_get_metrics_legacy_runs", lambda *args: legacy_reads.append(args) or [])

    assert surreal_db.calculate_metrics_dates()
    surreal_db.upsert_session(AgentSession(session_id="s2", agent_id="agent-1", created_at=noon_utc(utc_date(1))))
    assert surreal_db.calculate_metrics_dates()

    # The one read starts at the epoch, so it read every session
    assert [args[2].timestamp() for args in legacy_reads] == [0]


def test_calculate_metrics_leaves_a_day_that_conflicts_twice_to_the_next_calculation(
    surreal_db: SurrealDb, monkeypatch
):
    """Ensure a day whose write conflicts with another write twice is left open, and the refresh calculates the
    other days and completes"""
    build_dataset(surreal_db)
    surreal_db.calculate_metrics()
    old_day = utc_date(3)
    surreal_db.upsert_run(agent_run("alice_run_3", noon_utc(old_day) + 120, 1), "alice_session", "alice", 2)
    surreal_db.upsert_run(agent_run("alice_run_4", noon_utc(utc_date(2)), 1), "alice_session", "alice", 3)
    calculate_date_metrics = SurrealDb._calculate_date_metrics

    def _conflict_on_the_old_day(self, *args, **kwargs):
        if args[4] == old_day:
            raise Exception("Transaction conflict: Resource busy. This transaction can be retried")
        return calculate_date_metrics(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(SurrealDb, "_calculate_date_metrics", _conflict_on_the_old_day)
        calculated_dates = surreal_db.calculate_metrics_dates()

    assert calculated_dates is not None and old_day not in calculated_dates and utc_date(2) in calculated_dates
    assert (surreal_db.get_metrics_refresh_status() or {}).get("status") == "completed"
    assert old_day in (surreal_db.calculate_metrics_dates() or [])
