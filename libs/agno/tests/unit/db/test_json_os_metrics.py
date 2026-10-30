import time
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agno.db.json import JsonDb
from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession

COMPLETED = RunStatus.completed.value
ERROR = RunStatus.error.value


def utc_date(days_ago):
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def noon_utc(day):
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def agent_run(run_id, created_at, input_tokens, status=RunStatus.completed):
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(input_tokens=input_tokens, output_tokens=10, total_tokens=input_tokens + 10),
        created_at=created_at,
    )


def persist(db, session_id, user_id, day, runs):
    session = AgentSession(
        session_id=session_id, agent_id="agent-1", user_id=user_id, runs=runs, created_at=noon_utc(day)
    )
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run, session_id=session_id, user_id=user_id, run_index=run_index)


def stored_rows(db, table_name):
    return {(row["aggregation_period"], row["date"], row.get("user_id")): row for row in db._read_json_file(table_name)}


def stored_sessions(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    yesterday = utc_date(1)
    persist(
        db,
        "alice_session",
        "alice",
        yesterday,
        [
            agent_run("alice_run", noon_utc(yesterday), 100),
            agent_run("alice_error_run", noon_utc(yesterday) + 60, 20, status=RunStatus.error),
        ],
    )
    persist(db, "bob_session", "bob", yesterday, [agent_run("bob_run", noon_utc(yesterday) + 120, 200)])
    persist(db, "alice_today", "alice", utc_date(0), [agent_run("today_run", noon_utc(utc_date(0)), 1)])
    return db


def test_calculate_os_metrics_writes_rows_and_totals(tmp_path):
    db = stored_sessions(tmp_path)
    db.calculate_os_metrics()

    yesterday = utc_date(1).isoformat()
    today = utc_date(0).isoformat()
    rows = stored_rows(db, db.os_metrics_table_name)
    assert set(rows) == {("daily", yesterday, "alice"), ("daily", yesterday, "bob"), ("daily", today, "alice")}
    alice_row = rows[("daily", yesterday, "alice")]
    assert (alice_row["component_type"], alice_row["component_id"], alice_row["parent_component_id"]) == (
        "agent",
        "agent-1",
        "",
    )
    assert alice_row["sessions_count"] == 1
    assert alice_row["runs_count"] == 2
    assert alice_row["status_metrics"] == {COMPLETED: 1, ERROR: 1}
    assert alice_row["input_tokens"] == 120

    totals = stored_rows(db, db.os_metrics_totals_table_name)
    assert set(totals) == {("daily", yesterday, None), ("daily", today, None)}
    assert totals[("daily", yesterday, None)]["runs_count"] == 3
    assert totals[("daily", yesterday, None)]["input_tokens"] == 320
    assert [row["version"] for row in totals.values()] == [1, 1]
    assert [row["completed"] for row in totals.values()] == [False, False]


def test_calculate_os_metrics_counts_runs_kept_in_the_legacy_runs_field(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    yesterday = utc_date(1)
    in_both = agent_run("in_both", noon_utc(yesterday), 10).to_dict()
    legacy_only = agent_run("legacy_only", noon_utc(yesterday), 20).to_dict()
    db.upsert_session(
        AgentSession(session_id="legacy", agent_id="agent-1", user_id="alice", created_at=noon_utc(yesterday))
    )
    sessions = db._read_json_file(db.session_table_name)
    sessions[0]["runs"] = [in_both, legacy_only]
    db._write_json_file(db.session_table_name, sessions)
    db.upsert_run(in_both, session_id="legacy", user_id="alice", run_index=0)

    db.calculate_os_metrics()

    alice_row = stored_rows(db, db.os_metrics_table_name)[("daily", yesterday.isoformat(), "alice")]
    assert (alice_row["sessions_count"], alice_row["runs_count"], alice_row["input_tokens"]) == (1, 2, 30)


def test_get_os_metrics_reads_every_owner_and_one_owner(tmp_path):
    db = stored_sessions(tmp_path)
    db.calculate_os_metrics()

    yesterday = utc_date(1)
    today = utc_date(0)
    metrics, updated_at = db.get_os_metrics(
        starting_date=yesterday, ending_date=today, fields=["runs_count", "status_metrics"]
    )
    assert metrics == [
        {"date": yesterday, "runs_count": 3, "status_metrics": {COMPLETED: 2, ERROR: 1}},
        {"date": today, "runs_count": 1, "status_metrics": {COMPLETED: 1}},
    ]
    assert updated_at is not None

    metrics, _ = db.get_os_metrics(starting_date=yesterday, ending_date=today, user_id="bob")
    assert [(m["date"], m["runs_count"], m["input_tokens"]) for m in metrics] == [(yesterday, 1, 200)]

    totals, _ = db.get_os_metrics_totals(starting_date=yesterday, ending_date=today)
    assert (totals["runs_count"], totals["status_metrics"]) == (4, {COMPLETED: 3, ERROR: 1})


def test_refresh_os_metrics_reports_changes_and_moves_versions(tmp_path):
    db = stored_sessions(tmp_path)
    assert db.refresh_os_metrics()[2] is True
    versions = db.get_os_metrics_versions(utc_date(1), utc_date(0))
    assert versions == {f"daily {utc_date(1).isoformat()}": 1, f"daily {utc_date(0).isoformat()}": 1}

    _, _, changed = db.refresh_os_metrics()
    assert changed is False
    assert db.get_os_metrics_versions(utc_date(1), utc_date(0)) == versions

    db.upsert_run(agent_run("today_run_2", noon_utc(utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice")
    _, _, changed = db.refresh_os_metrics()
    assert changed is True
    assert db.get_os_metrics_versions(utc_date(1), utc_date(0)) == {
        f"daily {utc_date(1).isoformat()}": 1,
        f"daily {utc_date(0).isoformat()}": 2,
    }


def test_get_os_metrics_versions_is_none_while_incomplete(tmp_path):
    db = stored_sessions(tmp_path)
    db._os_metrics_refreshed_at = time.time()

    assert db.get_os_metrics_versions(utc_date(1), utc_date(0)) is None


def test_lazy_refresh_with_nothing_new_is_skipped(tmp_path):
    db = stored_sessions(tmp_path)
    later = max(time.time(), noon_utc(utc_date(0))) + 5

    with patch("agno.db.json.json_db.time", types.SimpleNamespace(time=lambda: later, sleep=time.sleep)):
        assert db._calculate_os_metrics(wait_for_rebuild=True) is not None
        assert db._calculate_os_metrics(wait_for_rebuild=False) is None

        db.upsert_run(
            agent_run("today_run_2", noon_utc(utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice"
        )
        assert db._calculate_os_metrics(wait_for_rebuild=False) is not None


def test_lazy_refresh_skips_while_another_rebuild_holds_the_lock(tmp_path):
    db = stored_sessions(tmp_path)
    token = db._lock_os_metrics(wait_for_rebuild=False)
    assert token is not None

    assert db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert db._os_metrics_refreshed_at == 0.0

    db._unlock_os_metrics(token)
    assert db._calculate_os_metrics(wait_for_rebuild=False) is not None


def test_completed_month_gets_month_rows(tmp_path):
    db = JsonDb(db_path=str(tmp_path))
    month_start = (utc_date(0).replace(day=1) - timedelta(days=32)).replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    persist(db, "first_session", "alice", month_start, [agent_run("first_run", noon_utc(month_start), 100)])
    persist(db, "last_session", "alice", month_end, [agent_run("last_run", noon_utc(month_end), 50)])

    db.calculate_os_metrics()

    month_row = stored_rows(db, db.os_metrics_table_name)[("monthly", month_start.isoformat(), "alice")]
    assert (month_row["sessions_count"], month_row["runs_count"], month_row["input_tokens"]) == (2, 2, 150)
    month_totals = stored_rows(db, db.os_metrics_totals_table_name)[("monthly", month_start.isoformat(), None)]
    assert (month_totals["runs_count"], month_totals["completed"], month_totals["version"]) == (2, True, 1)

    totals, _ = db.get_os_metrics_totals(starting_date=month_start, ending_date=month_end, user_id="alice")
    assert (totals["sessions_count"], totals["runs_count"], totals["input_tokens"]) == (2, 2, 150)
