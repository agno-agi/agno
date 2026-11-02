"""Tests for the component metrics methods of JsonDb, on JSON files in a temporary directory."""

import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.json import JsonDb
from agno.db.json import json_db as json_db_module
from agno.db.utils import METRICS_LOCK_SECONDS, METRICS_STOPPED_ERROR, calculate_date_metrics
from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession

COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value


def utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def noon_utc(day: date) -> int:
    """Midday UTC of ``day``, so a session or run dated there lands in that UTC day."""
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def run_metrics(input_tokens, cache_read_tokens=0):
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=10,
        total_tokens=input_tokens + 10,
        cache_read_tokens=cache_read_tokens,
    )


def agent_run(run_id, created_at, input_tokens, status=RunStatus.completed, agent_id="agent-1", **kwargs):
    return RunOutput(
        run_id=run_id,
        agent_id=agent_id,
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=run_metrics(input_tokens, kwargs.pop("cache_read_tokens", 0)),
        created_at=created_at,
        **kwargs,
    )


def persist(db, session, runs):
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def stored_rows(db, table_name):
    return {
        tuple(row[column] for column in ["aggregation_period", "date", "user_id"])
        + ((row["component_type"], row["component_id"]) if "component_type" in row else ()): row
        for row in db._read_metrics_file(table_name)
    }


def everyone_row(db, day, period="daily"):
    return stored_rows(db, db.user_metrics_table_name)[(period, day, "")]


def stored_sessions(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    yesterday = utc_date(1)
    persist(
        db,
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(yesterday)),
        [
            agent_run("alice_run", noon_utc(yesterday), 100),
            agent_run("alice_error_run", noon_utc(yesterday) + 60, 20, status=RunStatus.error),
        ],
    )
    persist(
        db,
        AgentSession(session_id="bob_session", agent_id="agent-1", user_id="bob", created_at=noon_utc(yesterday)),
        [agent_run("bob_run", noon_utc(yesterday) + 120, 200)],
    )
    persist(
        db,
        AgentSession(session_id="alice_today", agent_id="agent-1", user_id="alice", created_at=noon_utc(utc_date(0))),
        [agent_run("today_run", noon_utc(utc_date(0)), 1)],
    )
    return db


def set_locked_at(db, locked_at):
    refresh_rows = db._read_json_file(db.metrics_refreshes_table_name)
    db._write_json_file(db.metrics_refreshes_table_name, [{**refresh_rows[0], "locked_at": locked_at}])
    # The claim is the lock file, whose modification time is its last heartbeat
    os.utime(db.db_path / f"{db.metrics_refreshes_table_name}_lock.json", (locked_at, locked_at))


def store_session_without_metrics(db, day):
    sessions = db._read_json_file(db.session_table_name)
    sessions.append(
        {
            "session_id": "hidden",
            "session_type": "agent",
            "agent_id": "agent-1",
            "user_id": "alice",
            "created_at": noon_utc(day),
            "updated_at": noon_utc(day),
        }
    )
    db._write_json_file(db.session_table_name, sessions)


def _backdate(db: JsonDb) -> None:
    """Date every update of the sessions and runs to a minute ago, so none was updated in the current second."""
    for table_name in [db.session_table_name, db.runs_table_name]:
        rows = db._read_json_file(table_name)
        db._write_json_file(table_name, [{**row, "updated_at": int(time.time()) - 60} for row in rows])


# A dataset of an agent, a team with a member and a workflow, two users and no user, over three days


def build_dataset(db) -> List[Tuple[Any, Optional[str]]]:
    """Store the dataset, and return every stored run with its user."""
    old_day, yesterday, today = utc_date(3), utc_date(1), utc_date(0)
    alice_runs = [
        agent_run("alice_run", noon_utc(old_day), 100, cache_read_tokens=7),
        agent_run("alice_paused_run", noon_utc(old_day) + 60, 50, status=RunStatus.paused),
    ]
    persist(
        db,
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day)),
        alice_runs,
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

    workflow_run = WorkflowRunOutput(
        run_id="workflow_run", workflow_id="workflow-1", status=RunStatus.completed, created_at=noon_utc(today)
    )
    persist(
        db,
        WorkflowSession(session_id="workflow_session", workflow_id="workflow-1", created_at=noon_utc(today)),
        [workflow_run],
    )
    return [(run, "alice") for run in alice_runs] + [
        (team_run, "bob"),
        (member_run, "bob"),
        (workflow_run, None),
    ]


def ground_truth(runs: List[Tuple[Any, Optional[str]]]) -> Dict[Any, Dict[str, Any]]:
    """Count the given stored runs directly: per day, everyone and each user."""
    truth: Dict[Any, Dict[str, Any]] = {}
    for run, user_id in runs:
        day = datetime.fromtimestamp(run.created_at, tz=timezone.utc).date()
        run_type = (
            "team" if isinstance(run, TeamRunOutput) else "workflow" if isinstance(run, WorkflowRunOutput) else "agent"
        )
        metrics = run.metrics if getattr(run, "model", None) else None
        for key in [(day, ""), (day, user_id)] if user_id else [(day, "")]:
            counts = truth.setdefault(
                key,
                {
                    "agent_runs_count": 0,
                    "team_runs_count": 0,
                    "workflow_runs_count": 0,
                    "root_runs_count": 0,
                    "input_tokens": 0,
                    "cache_read_tokens": 0,
                },
            )
            counts[f"{run_type}_runs_count"] += 1
            counts["root_runs_count"] += 0 if run.parent_run_id else 1
            counts["input_tokens"] += metrics.input_tokens if metrics else 0
            counts["cache_read_tokens"] += metrics.cache_read_tokens if metrics else 0
    return truth


def assert_matches_ground_truth(db, runs):
    user_metrics_rows = stored_rows(db, db.user_metrics_table_name)
    for (day, user_id), counts in ground_truth(runs).items():
        row = user_metrics_rows[("daily", day, user_id)]
        assert {
            **{column: row[column] for column in counts if column != "cache_read_tokens"},
            "cache_read_tokens": row["token_details"].get("cache_read_tokens", 0),
        } == counts, (day, user_id)


def test_calculate_metrics_matches_a_direct_count_of_the_runs(tmp_path):
    """Ensure every day's user metrics rows match a direct count of the stored runs"""
    db = JsonDb(db_path=str(tmp_path))
    runs = build_dataset(db)

    calculated = db.calculate_metrics()

    old_day, yesterday, today = utc_date(3), utc_date(1), utc_date(0)
    assert {metric["date"] for metric in calculated} == {old_day, yesterday, today}
    assert_matches_ground_truth(db, runs)
    user_metrics_rows = stored_rows(db, db.user_metrics_table_name)
    assert user_metrics_rows[("daily", old_day, "")]["agent_sessions_count"] == 1
    assert user_metrics_rows[("daily", yesterday, "")]["team_sessions_count"] == 1
    assert user_metrics_rows[("daily", today, "")]["workflow_sessions_count"] == 1
    assert (
        user_metrics_rows[("daily", yesterday, "")]["users_count"],
        user_metrics_rows[("daily", today, "")]["users_count"],
    ) == (1, 0)
    assert user_metrics_rows[("daily", old_day, "")]["completed"] is True
    assert user_metrics_rows[("daily", yesterday, "")]["completed"] is False

    # The member run is counted under the team that started it
    rows = stored_rows(db, db.component_metrics_table_name)
    member_row = rows[("daily", yesterday, "bob", "agent", "member-1")]
    assert (member_row["parent_component_id"], member_row["root_component_id"]) == ("team-1", "team-1")

    # The runs with no user are read from their component rows
    metrics, _ = db.get_metrics(starting_date=today, ending_date=today, user_id="")
    assert [(metric["user_id"], metric["workflow_runs_count"]) for metric in metrics] == [(None, 1)]
    assert db.get_metrics_refresh_status()["status"] == "completed"


def test_calculate_metrics_rebuilds_a_reopened_day(tmp_path):
    """Ensure saving a run of a closed day reopens it, and the next calculation completes it again"""
    db = JsonDb(db_path=str(tmp_path))
    runs = build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(db, old_day)["version"]

    resumed_run = agent_run("alice_paused_run", noon_utc(old_day) + 60, 50)
    db.upsert_run(resumed_run, session_id="alice_session", user_id="alice")
    reopened_row = everyone_row(db, old_day)
    assert (reopened_row["completed"], reopened_row["version"]) == (False, version + 1)

    calculated = db.calculate_metrics()
    assert old_day in {metric["date"] for metric in calculated}
    row = everyone_row(db, old_day)
    assert row["completed"] is True
    assert row["status_metrics"] == {COMPLETED: 2}
    assert_matches_ground_truth(
        db, [(resumed_run, "alice") if run.run_id == "alice_paused_run" else (run, user) for run, user in runs]
    )


def test_session_save_reopens_the_day_the_session_is_stored_on(tmp_path):
    """Ensure a new session on a closed day reopens it, while saving the same session again does not"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(db, old_day)["version"]

    # Saving the same session again changes nothing it is counted under
    db.upsert_session(
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day))
    )
    assert everyone_row(db, old_day)["version"] == version

    db.upsert_session(
        AgentSession(session_id="late_session", agent_id="agent-1", user_id="carol", created_at=noon_utc(old_day))
    )
    assert (everyone_row(db, old_day)["completed"], everyone_row(db, old_day)["version"]) == (False, version + 1)


def test_delete_session_keeps_its_closed_day_closed(tmp_path):
    """Ensure deleting a session keeps its closed day closed"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    row = everyone_row(db, old_day)

    db.delete_session("alice_session")
    db.calculate_metrics()

    # The deleted usage is kept until the day is rebuilt for another reason
    assert everyone_row(db, old_day) == row


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(tmp_path):
    """Ensure rebuild_from rebuilds every day with data from it, including a day no write reopened"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(db, old_day)["version"]
    db.delete_session("alice_session")
    # A day with data the metrics never knew of: no write reopened it
    hidden_day = utc_date(5)
    store_session_without_metrics(db, hidden_day)
    db.calculate_metrics()
    assert ("daily", hidden_day, "") not in stored_rows(db, db.user_metrics_table_name)

    calculated_dates = db.calculate_metrics_dates(rebuild_from=hidden_day)

    assert set(calculated_dates) >= {hidden_day, old_day, utc_date(1), utc_date(0)}
    assert everyone_row(db, hidden_day)["agent_sessions_count"] == 1
    row = everyone_row(db, old_day)
    assert (row["agent_runs_count"], row["completed"]) == (0, True)
    assert row["version"] > version


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_field(tmp_path):
    """Ensure a run kept only in the legacy runs field is counted once, on its own day"""
    db = JsonDb(db_path=str(tmp_path))
    session_day, run_day, yesterday = utc_date(6), utc_date(4), utc_date(1)
    in_both = agent_run("in_both", noon_utc(yesterday), 10).to_dict()
    legacy_only = agent_run("legacy_only", noon_utc(yesterday), 20).to_dict()
    member_run = agent_run("member_run", noon_utc(yesterday) + 5, 20, agent_id="member-1", parent_run_id="team_run")
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=run_metrics(30),
        member_responses=[member_run],
        created_at=noon_utc(yesterday),
    )
    db.upsert_session(
        AgentSession(session_id="legacy", agent_id="agent-1", user_id="alice", created_at=noon_utc(yesterday))
    )
    db.upsert_session(
        AgentSession(session_id="legacy_old", agent_id="agent-1", user_id="alice", created_at=noon_utc(session_day))
    )
    db.upsert_session(
        TeamSession(session_id="legacy_team", team_id="team-1", user_id="bob", created_at=noon_utc(yesterday))
    )
    legacy_runs = {
        "legacy": [in_both, legacy_only],
        "legacy_old": [agent_run("legacy_run", noon_utc(run_day), 20).to_dict()],
        # The legacy runs field keeps the member run inside the team run and as a run of its own
        "legacy_team": [team_run.to_dict(), member_run.to_dict()],
    }
    sessions = db._read_json_file(db.session_table_name)
    db._write_json_file(
        db.session_table_name, [{**session, "runs": legacy_runs[session["session_id"]]} for session in sessions]
    )
    db.upsert_run(in_both, session_id="legacy", user_id="alice", run_index=0)
    # Not yet migrated to v3.0.0, so the legacy runs are read
    db.upsert_schema_version(db.session_table_name, "2.5.0")

    calculated_dates = db.calculate_metrics_dates()

    # A first calculation builds the own day of a legacy run
    assert {session_day, run_day} <= set(calculated_dates)
    assert everyone_row(db, run_day)["agent_runs_count"] == 1
    alice_row = stored_rows(db, db.component_metrics_table_name)[("daily", yesterday, "alice", "agent", "agent-1")]
    assert (alice_row["sessions_count"], alice_row["runs_count"], alice_row["input_tokens"]) == (1, 2, 30)
    # A legacy team member run is counted once
    bob_row = stored_rows(db, db.user_metrics_table_name)[("daily", yesterday, "bob")]
    assert (bob_row["team_runs_count"], bob_row["agent_runs_count"], bob_row["input_tokens"]) == (1, 1, 50)

    # Once the v3.0.0 migration is stamped, the legacy runs field is a backup only
    db.upsert_schema_version(db.session_table_name, "3.0.0")
    db.calculate_metrics(rebuild_from=yesterday)
    alice_row = stored_rows(db, db.component_metrics_table_name)[("daily", yesterday, "alice", "agent", "agent-1")]
    assert (alice_row["runs_count"], alice_row["input_tokens"]) == (1, 10)


@pytest.mark.parametrize("legacy_runs_count", [0, 1])
def test_calculate_metrics_reads_the_legacy_runs_while_a_session_holds_some(tmp_path, monkeypatch, legacy_runs_count):
    """Ensure an unstamped store reads the legacy runs once when none are held, and every time while one is"""
    db = JsonDb(db_path=str(tmp_path))
    yesterday = utc_date(1)
    db.upsert_session(
        AgentSession(session_id="legacy", agent_id="agent-1", user_id="alice", created_at=noon_utc(yesterday))
    )
    legacy_runs = [agent_run("legacy_run", noon_utc(yesterday), 20).to_dict()][:legacy_runs_count]
    db._write_json_file(
        db.session_table_name,
        [{**session, "runs": legacy_runs} for session in db._read_json_file(db.session_table_name)],
    )
    # A store created on 3.0 or 3.1 stamps no schema version
    db._write_json_file(db.versions_table_name, [])
    reads = []
    get_metrics_legacy_runs = json_db_module.get_metrics_legacy_runs
    monkeypatch.setattr(
        json_db_module, "get_metrics_legacy_runs", lambda sessions: reads.append(1) or get_metrics_legacy_runs(sessions)
    )

    db.calculate_metrics_dates(rebuild_from=yesterday)
    for index in range(2):
        # A new run today changes the fingerprint, so yesterday and today are rebuilt
        persist(
            db,
            AgentSession(
                session_id=f"new_{index}", agent_id="agent-1", user_id="bob", created_at=noon_utc(utc_date(0))
            ),
            [agent_run(f"new_run_{index}", noon_utc(utc_date(0)), 10)],
        )
        db.calculate_metrics_dates()
        assert everyone_row(db, yesterday)["agent_runs_count"] == legacy_runs_count

    assert len(reads) == (3 if legacy_runs_count else 1)


def test_get_component_metrics_reads_every_owner_and_one_owner(tmp_path):
    """Ensure the component metrics read every owner, one owner, and each user"""
    db = stored_sessions(tmp_path)
    db.calculate_metrics()

    yesterday, today = utc_date(1), utc_date(0)
    metrics, updated_at = db.get_component_metrics(
        starting_date=yesterday, ending_date=today, fields=["root_runs_count", "status_metrics"]
    )
    assert metrics == [
        {"date": yesterday, "root_runs_count": 3, "status_metrics": {COMPLETED: 2, ERROR: 1}},
        {"date": today, "root_runs_count": 1, "status_metrics": {COMPLETED: 1}},
    ]
    assert updated_at is not None

    metrics, _ = db.get_component_metrics(starting_date=yesterday, ending_date=today, user_id="bob")
    assert [(m["date"], m["root_runs_count"], m["input_tokens"]) for m in metrics] == [(yesterday, 1, 200)]

    totals, _ = db.get_metrics_totals(starting_date=yesterday, ending_date=today)
    assert (totals["root_runs_count"], totals["status_metrics"]) == (4, {COMPLETED: 3, ERROR: 1})

    metrics, _ = db.get_metrics(starting_date=yesterday, ending_date=yesterday)
    assert [(m["user_id"], m["agent_runs_count"]) for m in metrics] == [("alice", 2), ("bob", 1)]
    metrics, _ = db.get_metrics_by_date(starting_date=yesterday, ending_date=yesterday)
    assert [(m["user_id"], m["agent_runs_count"], m["users_count"]) for m in metrics] == [(None, 3, 2)]


def test_calculate_metrics_skips_a_refresh_with_nothing_new(tmp_path):
    """Ensure a calculation skips the rebuild while no session or run changed"""
    db = stored_sessions(tmp_path)
    _backdate(db)
    assert db.calculate_metrics()
    assert db.calculate_metrics_dates() == []
    # Nothing changed, so calculate_metrics returns today's metrics as they are
    assert [(metric["date"], metric["user_id"]) for metric in db.calculate_metrics()] == [(utc_date(0), "alice")]


def test_get_metrics_reads_the_metrics_file_until_the_first_calculation_finished(tmp_path):
    """Ensure a read never runs a first calculation, and reads the metrics file once one finished"""
    db = stored_sessions(tmp_path)

    # A read never runs a first calculation, which reads every run
    assert db.get_metrics() == ([], None)
    assert db._get_metrics_refresh_row()[0] is None

    db.calculate_metrics()
    metrics, _ = db.get_metrics(starting_date=utc_date(1), ending_date=utc_date(1))
    assert [(m["user_id"], m["agent_runs_count"]) for m in metrics] == [("alice", 2), ("bob", 1)]


def test_calculate_metrics_writes_a_month_user_metrics_row_for_a_completed_month(tmp_path):
    """Ensure a completed month gets its month user metrics rows"""
    db = JsonDb(db_path=str(tmp_path))
    month_start = (utc_date(0).replace(day=1) - timedelta(days=32)).replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    persist(
        db,
        AgentSession(session_id="first", agent_id="agent-1", user_id="alice", created_at=noon_utc(month_start)),
        [agent_run("first_run", noon_utc(month_start), 100)],
    )
    persist(
        db,
        AgentSession(session_id="last", agent_id="agent-1", user_id="alice", created_at=noon_utc(month_end)),
        [agent_run("last_run", noon_utc(month_end), 50)],
    )

    db.calculate_metrics()

    month_row = everyone_row(db, month_start, period="monthly")
    assert (month_row["agent_runs_count"], month_row["completed"], month_row["version"]) == (2, True, 1)
    assert month_row["users_count"] == 1

    totals, _ = db.get_metrics_totals(starting_date=month_start, ending_date=month_end, user_id="alice")
    assert (totals["sessions_count"], totals["root_runs_count"], totals["input_tokens"]) == (2, 2, 150)


def test_calculate_metrics_dates_releases_the_lock_when_stopped(tmp_path):
    """Ensure a stopped calculation writes the days it calculated and releases the lock"""
    db = stored_sessions(tmp_path)
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) > 1

    assert db.calculate_metrics_dates(should_stop=should_stop) is None
    assert ("daily", utc_date(1), "") in stored_rows(db, db.user_metrics_table_name)
    assert ("daily", utc_date(0), "") not in stored_rows(db, db.user_metrics_table_name)
    assert db.get_metrics_refresh_status()["status"] == "failed"
    assert db.calculate_metrics() is not None

    # A stopped calculation keeps the status of the last completed one
    db.upsert_run(agent_run("today_run_2", noon_utc(utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice")
    _backdate(db)
    assert db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)


def test_a_run_save_never_fails_because_of_metrics(tmp_path):
    """Ensure a run save never fails when its day cannot be reopened, and the next write reopens it"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    user_metrics_path = tmp_path / f"{db.user_metrics_table_name}.json"
    stored_user_metrics = user_metrics_path.read_text()
    user_metrics_path.write_text("not json")

    db.upsert_run(
        agent_run("alice_paused_run", noon_utc(old_day) + 60, 50), session_id="alice_session", user_id="alice"
    )
    assert db._metrics_days_not_reopened == {old_day}

    # The next write reopens it
    user_metrics_path.write_text(stored_user_metrics)
    db.upsert_run(agent_run("today_run", noon_utc(utc_date(0)), 1), session_id="alice_session", user_id="alice")
    assert db._metrics_days_not_reopened == set()
    assert everyone_row(db, old_day)["completed"] is False


def test_a_run_save_before_any_calculation_creates_no_metrics_file(tmp_path):
    """Ensure a run save before any calculation creates no metrics file"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)

    assert not (tmp_path / f"{db.user_metrics_table_name}.json").exists()
    assert db._metrics_days_not_reopened == set()


@pytest.mark.parametrize("metrics_table", [None, "custom_metrics"])
def test_metrics_table_names(tmp_path, metrics_table):
    """Ensure the metrics table names follow the session table, with or without metrics_table"""
    db = JsonDb(db_path=str(tmp_path), session_table="custom_sessions", metrics_table=metrics_table)
    assert (db.component_metrics_table_name, db.user_metrics_table_name) == (
        "custom_sessions_component_metrics",
        "custom_sessions_user_metrics",
    )


def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(monkeypatch, tmp_path):
    """Ensure a day reopened while it is rebuilt stays open for the next calculation"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    db.calculate_metrics(rebuild_from=old_day)
    assert everyone_row(db, old_day)["completed"] is True

    def calculate_and_save(rows_by_key, date_to_process, *args):
        if date_to_process == old_day:
            # Saved after the calculation read the day's runs
            db.upsert_run(
                agent_run("alice_paused_run", noon_utc(old_day) + 60, 50), session_id="alice_session", user_id="alice"
            )
        return calculate_date_metrics(rows_by_key, date_to_process, *args)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.json.json_db.calculate_date_metrics", calculate_and_save)
        db.calculate_metrics(rebuild_from=old_day)

    assert everyone_row(db, old_day)["completed"] is False
    db.calculate_metrics()
    row = everyone_row(db, old_day)
    assert (row["completed"], row["status_metrics"]) == (True, {COMPLETED: 2})


def test_calculate_metrics_skips_a_rebuild_already_running(tmp_path):
    """Ensure a calculation returns None while another worker holds the refresh"""
    db = stored_sessions(tmp_path)
    assert db._claim_metrics_refresh("another-worker") is not None
    assert db._claim_metrics_refresh("a-third-worker") is None

    assert db.calculate_metrics() is None
    assert db.get_metrics_refresh_status()["status"] == "running"
    assert db._heartbeat_metrics_refresh("a-third-worker") is False
    assert db._heartbeat_metrics_refresh("another-worker") is True

    db._release_metrics_refresh("another-worker", error="stopped")
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"], status["finished_at"]) == ("failed", "stopped", None)
    assert db.calculate_metrics()
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)
    assert status["finished_at"] is not None


def test_claim_metrics_refresh_returns_none_when_its_lock_file_never_reads(tmp_path):
    """Ensure a lock file that can be neither created nor read returns None instead of retrying forever"""
    db = stored_sessions(tmp_path)
    os.symlink(db.db_path / "missing.json", db.db_path / f"{db.metrics_refreshes_table_name}_lock.json")

    assert db._claim_metrics_refresh("another-worker") is None


def test_calculate_metrics_takes_over_a_lock_that_went_stale(tmp_path):
    """Ensure a stale refresh reads as failed and the next calculation takes it over"""
    db = stored_sessions(tmp_path)
    db._claim_metrics_refresh("stopped-worker")
    set_locked_at(db, int(time.time()) - METRICS_LOCK_SECONDS)
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)

    assert db.calculate_metrics()
    assert db.get_metrics_refresh_status()["status"] == "completed"
    assert db._heartbeat_metrics_refresh("stopped-worker") is False


def test_calculate_metrics_records_a_failed_refresh(monkeypatch, tmp_path):
    """Ensure a failed refresh records its error and keeps no finished_at"""
    db = stored_sessions(tmp_path)

    def fail(*args):
        raise ValueError("boom")

    monkeypatch.setattr("agno.db.json.json_db.calculate_date_metrics", fail)
    with pytest.raises(ValueError):
        db.calculate_metrics()
    refresh_row = db._get_metrics_refresh_row()[0]
    assert (refresh_row["status"], refresh_row["error"], refresh_row["finished_at"]) == ("failed", "boom", None)
    assert refresh_row["locked_by"] is None


def test_get_metrics_omits_a_day_without_sessions_or_runs(tmp_path):
    """Ensure a day without sessions or runs is omitted from the metrics read"""
    db = JsonDb(db_path=str(tmp_path))
    old_day = utc_date(3)
    persist(
        db,
        AgentSession(session_id="old", agent_id="agent-1", user_id="alice", created_at=noon_utc(old_day)),
        [agent_run("old_run", noon_utc(old_day), 10)],
    )
    db.calculate_metrics()

    # Yesterday and today keep an everyone row of zeros
    assert everyone_row(db, utc_date(1))["agent_runs_count"] == 0
    metrics, _ = db.get_metrics_by_date(starting_date=old_day, ending_date=utc_date(0))
    assert [metric["date"] for metric in metrics] == [old_day]


def test_metrics_calculation_disabled_stops_the_refresh_on_read(monkeypatch, tmp_path):
    """Ensure no refresh runs on read while metrics calculation is disabled or AgentOS calculates them"""
    db = stored_sessions(tmp_path)
    db.calculate_metrics()
    calculations = []
    monkeypatch.setattr(db, "calculate_metrics_dates", lambda *args, **kwargs: calculations.append(1))

    monkeypatch.setenv("METRICS_CALCULATION_ENABLED", "false")
    db._metrics_refreshed_at = 0.0
    db.get_metrics()
    assert calculations == []

    monkeypatch.setenv("METRICS_CALCULATION_ENABLED", "true")
    db._metrics_refreshed_at = 0.0
    db.get_metrics()
    assert calculations == [1]

    # AgentOS calculates them in the background
    db.stop_metrics_refresh_on_read()
    db.get_metrics()
    assert calculations == [1]


def test_a_run_save_keeps_the_first_created_at_of_its_run(tmp_path):
    """Ensure saving a run again keeps the created_at it was first stored with"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    old_day = utc_date(3)
    db.upsert_run(
        agent_run("alice_paused_run", noon_utc(old_day) + 600, 50), session_id="alice_session", user_id="alice"
    )
    stored_run = next(run for run in db._read_runs_file() if run["run_id"] == "alice_paused_run")
    assert stored_run["created_at"] == noon_utc(old_day) + 60


def test_calculate_metrics_rebuilds_a_month_a_stopped_calculation_left(monkeypatch, tmp_path):
    """Ensure a month left open by a stopped calculation is read from its days and rebuilt next"""
    db = JsonDb(db_path=str(tmp_path))
    month_start = (utc_date(0).replace(day=1) - timedelta(days=32)).replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    persist(
        db,
        AgentSession(session_id="first", agent_id="agent-1", user_id="alice", created_at=noon_utc(month_start)),
        [agent_run("first_run", noon_utc(month_start), 100)],
    )
    db.calculate_metrics()
    assert everyone_row(db, month_start, period="monthly")["completed"] is True

    db.upsert_run(agent_run("late_run", noon_utc(month_start) + 60, 1000), session_id="first", user_id="alice")
    # Stopped after its days, before its months
    monkeypatch.setattr("agno.db.json.json_db.get_months_to_calculate_metrics_for", lambda days: [])
    monkeypatch.setattr("agno.db.json.json_db.get_open_metrics_months", lambda user_metrics_by_key: [])
    db.calculate_metrics()
    monkeypatch.undo()

    assert everyone_row(db, month_start, period="monthly")["completed"] is False
    # An open month is read from its days
    totals, _ = db.get_metrics_totals(starting_date=month_start, ending_date=month_end, fields=["input_tokens"])
    assert totals["input_tokens"] == 1100

    db.calculate_metrics()
    month_row = everyone_row(db, month_start, period="monthly")
    assert (month_row["completed"], month_row["input_tokens"]) == (True, 1100)


def test_get_metrics_versions_move_for_a_reopened_day_that_is_rebuilt(tmp_path):
    """Ensure no version is read before a first calculation, and a rebuilt day's version moves"""
    db = JsonDb(db_path=str(tmp_path))
    build_dataset(db)
    old_day = utc_date(3)
    assert db.get_metrics_versions(old_day, utc_date(0)) is None

    db.calculate_metrics()
    versions = db.get_metrics_versions(old_day, utc_date(0))
    assert {key for key in versions if key.startswith("daily")} == {
        f"daily {day.isoformat()}" for day in [old_day, utc_date(1), utc_date(0)]
    }
    assert versions[f"daily {old_day.isoformat()}"] == everyone_row(db, old_day)["version"]

    db.upsert_run(
        agent_run("alice_paused_run", noon_utc(old_day) + 60, 50), session_id="alice_session", user_id="alice"
    )
    db.calculate_metrics()
    new_versions = db.get_metrics_versions(old_day, old_day)
    assert new_versions == {f"daily {old_day.isoformat()}": everyone_row(db, old_day)["version"]}
    assert new_versions[f"daily {old_day.isoformat()}"] > versions[f"daily {old_day.isoformat()}"]


def test_calculate_metrics_builds_no_month_row_before_its_last_day_can_be_completed(tmp_path):
    """Ensure the current month's user metrics row is left open and unbuilt, as its last day cannot be completed yet"""
    db = stored_sessions(tmp_path)

    db.calculate_metrics()

    month_row = everyone_row(db, utc_date(0).replace(day=1), period="monthly")
    assert (month_row["completed"], month_row["input_tokens"]) == (False, 0)


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_completes(tmp_path):
    """Ensure rebuild_from leaves yesterday and today to the next calculation when another process holds the metrics
    refresh and completes it with the fingerprint it read before the rebuild"""
    db = JsonDb(db_path=str(tmp_path))
    persist(
        db,
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=noon_utc(utc_date(3))),
        [agent_run("alice_run", noon_utc(utc_date(3)), 100)],
    )
    _backdate(db)
    db.calculate_metrics()
    refresh_row = db._claim_metrics_refresh("other_process")
    assert refresh_row is not None

    assert db.calculate_metrics(rebuild_from=utc_date(3)) is None

    db._release_metrics_refresh(
        "other_process", fingerprint=refresh_row["fingerprint"], claimed_fingerprint=refresh_row["fingerprint"]
    )
    assert db.calculate_metrics_dates() == [utc_date(3), utc_date(1), utc_date(0)]
    assert db.calculate_metrics_dates() == []


def test_a_heartbeat_keeps_a_fingerprint_marked_since_its_read(monkeypatch, tmp_path):
    """Ensure a fingerprint rebuild_from marks between a heartbeat's read and its write stays marked"""
    db = stored_sessions(tmp_path)
    _backdate(db)
    db.calculate_metrics()
    assert db._claim_metrics_refresh("worker")["fingerprint"] is not None
    read_json_file = db._read_json_file
    reads = []

    def read_then_rebuild(filename, create_table_if_not_found=True):
        result = read_json_file(filename, create_table_if_not_found)
        if filename == db.metrics_refreshes_table_name and not reads:
            reads.append(filename)
            # Another process marks the fingerprint between the heartbeat's read of the refresh and its write
            assert JsonDb(db_path=str(tmp_path)).calculate_metrics(rebuild_from=utc_date(1)) is None
        return result

    monkeypatch.setattr(db, "_read_json_file", read_then_rebuild)
    assert db._heartbeat_metrics_refresh("worker") is True
    monkeypatch.undo()

    assert db._get_metrics_refresh_row()[0]["fingerprint"][0] == "rebuild"


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_claimed_no_fingerprint(
    tmp_path,
):
    """Ensure rebuild_from, run while a calculation that claimed no fingerprint holds the metrics refresh, leaves
    yesterday and today to the next calculation"""
    db = stored_sessions(tmp_path)
    _backdate(db)
    rebuilds = []

    def rebuild_once():
        if not rebuilds:
            rebuilds.append(JsonDb(db_path=str(tmp_path)).calculate_metrics_dates(rebuild_from=utc_date(1)))
        return False

    assert db.calculate_metrics_dates(should_stop=rebuild_once) == [utc_date(1), utc_date(0)]
    assert rebuilds == [None]
    assert db.calculate_metrics_dates() == [utc_date(1), utc_date(0)]
    assert db.calculate_metrics_dates() == []


def test_calculate_metrics_rebuild_from_records_a_failed_reopen(monkeypatch, tmp_path):
    """Ensure rebuild_from that fails to reopen its days shows the error on the metrics refresh no process holds,
    before any refresh too"""
    db = stored_sessions(tmp_path)

    def fail(user_metrics_by_key, starting_date):
        raise RuntimeError("reopen failed")

    # Before any refresh there is no row, so the failed one is created
    with monkeypatch.context() as patch:
        patch.setattr("agno.db.json.json_db.reopen_metrics_days_from", fail)
        with pytest.raises(RuntimeError):
            db.calculate_metrics_dates(rebuild_from=utc_date(1))

    refresh_row = db._get_metrics_refresh_row()[0]
    assert (refresh_row["status"], refresh_row["error"], refresh_row["locked_by"]) == ("failed", "reopen failed", None)

    db.calculate_metrics()
    monkeypatch.setattr("agno.db.json.json_db.reopen_metrics_days_from", fail)
    with pytest.raises(RuntimeError):
        db.calculate_metrics_dates(rebuild_from=utc_date(1))

    refresh_row = db._get_metrics_refresh_row()[0]
    assert (refresh_row["status"], refresh_row["error"], refresh_row["locked_by"]) == ("failed", "reopen failed", None)


def test_calculate_metrics_names_a_remote_member_run_the_day_after_its_team_run(tmp_path):
    """Ensure a remote member's run, stored with no parent the day after its team's run, names that team"""
    db = JsonDb(db_path=str(tmp_path))
    team_day, member_day = utc_date(3), utc_date(2)
    member_session_id = "team_session:remote-agent"
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        session_id="team_session",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=run_metrics(30),
        member_responses=[
            agent_run(
                "member_run",
                noon_utc(member_day),
                20,
                agent_id="remote-agent",
                session_id=member_session_id,
                parent_run_id="team_run",
            )
        ],
        created_at=noon_utc(team_day),
    )
    persist(db, TeamSession(session_id="team_session", team_id="team-1", created_at=noon_utc(team_day)), [team_run])
    # The remote AgentOS stores the member run with no parent
    persist(
        db,
        AgentSession(session_id=member_session_id, agent_id="remote-agent", created_at=noon_utc(member_day)),
        [agent_run("member_run", noon_utc(member_day), 20, agent_id="remote-agent", session_id=member_session_id)],
    )

    db.calculate_metrics()

    row = stored_rows(db, db.component_metrics_table_name)[("daily", member_day, "", "agent", "remote-agent")]
    assert (row["parent_component_id"], row["root_component_id"]) == ("team-1", "team-1")
