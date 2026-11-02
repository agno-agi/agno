"""Tests for the component metrics methods of InMemoryDb."""

import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.in_memory import InMemoryDb
from agno.db.utils import METRICS_LOCK_SECONDS, METRICS_STOPPED_ERROR
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
        for row in {
            db.component_metrics_table_name: db._component_metrics,
            db.user_metrics_table_name: db._user_metrics,
        }[table_name]
    }


def everyone_row(db, day, period="daily"):
    return stored_rows(db, db.user_metrics_table_name)[(period, day, "")]


def stored_sessions():
    db = InMemoryDb()
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
    db._metrics_refreshes = [{**db._metrics_refreshes[0], "locked_at": locked_at}]


def _backdate(db: InMemoryDb) -> None:
    """Date every update of the sessions and runs to a minute ago, so none was updated in the current second."""
    for session in db._sessions.values():
        session["updated_at"] = int(time.time()) - 60
        for run in session.get("runs") or []:
            run["updated_at"] = int(time.time()) - 60


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
    totals = stored_rows(db, db.user_metrics_table_name)
    for (day, user_id), counts in ground_truth(runs).items():
        row = totals[("daily", day, user_id)]
        assert {
            **{column: row[column] for column in counts if column != "cache_read_tokens"},
            "cache_read_tokens": row["token_details"].get("cache_read_tokens", 0),
        } == counts, (day, user_id)


def test_calculate_metrics_matches_a_direct_count_of_the_runs():
    """Ensure every day's totals rows match a direct count of the stored runs"""
    db = InMemoryDb()
    runs = build_dataset(db)

    calculated = db.calculate_metrics()

    old_day, yesterday, today = utc_date(3), utc_date(1), utc_date(0)
    assert {metric["date"] for metric in calculated} == {old_day, yesterday, today}
    assert_matches_ground_truth(db, runs)
    totals = stored_rows(db, db.user_metrics_table_name)
    assert totals[("daily", old_day, "")]["agent_sessions_count"] == 1
    assert totals[("daily", yesterday, "")]["team_sessions_count"] == 1
    assert totals[("daily", today, "")]["workflow_sessions_count"] == 1
    assert (totals[("daily", yesterday, "")]["users_count"], totals[("daily", today, "")]["users_count"]) == (1, 0)
    assert totals[("daily", old_day, "")]["completed"] is True
    assert totals[("daily", yesterday, "")]["completed"] is False

    # The member run is counted under the team that started it
    rows = stored_rows(db, db.component_metrics_table_name)
    member_row = rows[("daily", yesterday, "bob", "agent", "member-1")]
    assert (member_row["parent_component_id"], member_row["root_component_id"]) == ("team-1", "team-1")

    # The runs with no user are read from their component rows
    metrics, _ = db.get_metrics(starting_date=today, ending_date=today, user_id="")
    assert [(metric["user_id"], metric["workflow_runs_count"]) for metric in metrics] == [(None, 1)]
    assert db.get_metrics_refresh_status()["status"] == "completed"


def test_a_run_save_reopens_its_closed_day():
    """Ensure saving a run of a closed day reopens it, and the next calculation completes it again"""
    db = InMemoryDb()
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


def test_a_new_session_on_a_closed_day_reopens_it():
    """Ensure a new session on a closed day reopens it, while saving the same session again does not"""
    db = InMemoryDb()
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


def test_a_delete_does_not_reopen_its_day():
    """Ensure deleting a session keeps its closed day closed"""
    db = InMemoryDb()
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    row = everyone_row(db, old_day)

    db.delete_session("alice_session")
    db.calculate_metrics()

    # The deleted usage is kept until the day is rebuilt for another reason
    assert everyone_row(db, old_day) == row


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from():
    """Ensure rebuild_from rebuilds every day with data from it, including a day no write reopened"""
    db = InMemoryDb()
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    version = everyone_row(db, old_day)["version"]
    db.delete_session("alice_session")

    calculated_dates = db.calculate_metrics_dates(rebuild_from=old_day)

    assert set(calculated_dates) >= {old_day, utc_date(1), utc_date(0)}
    row = everyone_row(db, old_day)
    assert (row["agent_runs_count"], row["completed"]) == (0, True)
    assert row["version"] > version


def test_calculate_metrics_skips_a_refresh_with_nothing_new():
    """Ensure a calculation skips the rebuild while no session or run changed"""
    db = stored_sessions()
    _backdate(db)
    assert db.calculate_metrics()
    assert db.calculate_metrics_dates() == []


def test_get_metrics_reads_the_metrics_rows_until_the_first_calculation_finished():
    """Ensure a read never runs a first calculation, and reads the metrics rows once one finished"""
    db = stored_sessions()

    # A read never runs a first calculation, which reads every run
    assert db.get_metrics() == ([], None)
    assert db._get_metrics_refresh_row()[0] is None

    db.calculate_metrics()
    metrics, _ = db.get_metrics(starting_date=utc_date(1), ending_date=utc_date(1))
    assert [(m["user_id"], m["agent_runs_count"]) for m in metrics] == [("alice", 2), ("bob", 1)]


def test_a_stopped_calculation_writes_its_days_and_releases_the_lock():
    """Ensure a stopped calculation writes the days it calculated and releases the lock"""
    db = stored_sessions()
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) > 1

    assert db.calculate_metrics_dates(should_stop=should_stop) is None
    assert ("daily", utc_date(1), "") in stored_rows(db, db.user_metrics_table_name)
    assert ("daily", utc_date(0), "") not in stored_rows(db, db.user_metrics_table_name)
    assert db.get_metrics_refresh_status()["status"] == "failed"
    assert db.calculate_metrics() is not None


def test_a_run_save_never_fails_because_of_metrics():
    """Ensure a run save never fails when its day cannot be reopened, and the next write reopens it"""
    db = InMemoryDb()
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    stored_totals = db._user_metrics
    db._user_metrics = [{"broken": True}]

    db.upsert_run(
        agent_run("alice_paused_run", noon_utc(old_day) + 60, 50), session_id="alice_session", user_id="alice"
    )
    assert db._metrics_days_not_reopened == {old_day}

    # The next write reopens it
    db._user_metrics = stored_totals
    db.upsert_run(agent_run("today_run", noon_utc(utc_date(0)), 1), session_id="alice_session", user_id="alice")
    assert db._metrics_days_not_reopened == set()
    assert everyone_row(db, old_day)["completed"] is False


def test_a_run_save_before_any_calculation_creates_no_metrics_rows():
    """Ensure a run save before any calculation creates no metrics rows"""
    db = InMemoryDb()
    build_dataset(db)

    assert db._user_metrics is None
    assert db._metrics_days_not_reopened == set()


def test_calculate_metrics_keeps_a_day_reopened_during_its_rebuild_open(monkeypatch):
    """Ensure a day reopened while it is rebuilt stays open for the next calculation"""
    db = InMemoryDb()
    build_dataset(db)
    db.calculate_metrics()
    old_day = utc_date(3)
    db.calculate_metrics(rebuild_from=old_day)
    assert everyone_row(db, old_day)["completed"] is True

    calculate_day_metrics = sys.modules[type(db).__module__].calculate_day_metrics

    def calculate_and_save(rows_by_key, date_to_process, *args):
        if date_to_process == old_day:
            # Saved after the calculation read the day's runs
            db.upsert_run(
                agent_run("alice_paused_run", noon_utc(old_day) + 60, 50), session_id="alice_session", user_id="alice"
            )
        return calculate_day_metrics(rows_by_key, date_to_process, *args)

    with monkeypatch.context() as patch:
        patch.setattr(sys.modules[type(db).__module__], "calculate_day_metrics", calculate_and_save)
        db.calculate_metrics(rebuild_from=old_day)

    assert everyone_row(db, old_day)["completed"] is False
    db.calculate_metrics()
    row = everyone_row(db, old_day)
    assert (row["completed"], row["status_metrics"]) == (True, {COMPLETED: 2})


def test_calculate_metrics_returns_none_while_another_worker_holds_the_refresh():
    """Ensure a calculation returns None while another worker holds the refresh"""
    db = stored_sessions()
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


def test_a_stale_refresh_reads_failed_and_is_taken_over():
    """Ensure a stale refresh reads as failed and the next calculation takes it over"""
    db = stored_sessions()
    db._claim_metrics_refresh("stopped-worker")
    set_locked_at(db, int(time.time()) - METRICS_LOCK_SECONDS)
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)

    assert db.calculate_metrics()
    assert db.get_metrics_refresh_status()["status"] == "completed"
    assert db._heartbeat_metrics_refresh("stopped-worker") is False


def test_a_failed_refresh_keeps_no_finished_at(monkeypatch):
    """Ensure a failed refresh records its error and keeps no finished_at"""
    db = stored_sessions()

    def fail(*args):
        raise ValueError("boom")

    monkeypatch.setattr(sys.modules[type(db).__module__], "calculate_day_metrics", fail)
    with pytest.raises(ValueError):
        db.calculate_metrics()
    refresh_row = db._get_metrics_refresh_row()[0]
    assert (refresh_row["status"], refresh_row["error"], refresh_row["finished_at"]) == ("failed", "boom", None)
    assert refresh_row["locked_by"] is None


def test_metrics_calculation_disabled_stops_the_refresh_on_read(monkeypatch):
    """Ensure no refresh runs on read while metrics calculation is disabled or AgentOS calculates them"""
    db = stored_sessions()
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


def test_get_metrics_versions_move_for_a_reopened_day_that_is_rebuilt():
    """Ensure no version is read before a first calculation, and a rebuilt day's version moves"""
    db = InMemoryDb()
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
