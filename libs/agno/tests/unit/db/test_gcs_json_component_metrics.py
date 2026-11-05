"""Tests for the component metrics methods of GcsJsonDb.

Uses a tiny in-memory stub for the GCS client/bucket/blob trio, keeping a
generation per object as GCS does, so no real GCS account is needed.
"""

import time
import types
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.utils import METRICS_LOCK_SECONDS, METRICS_STOPPED_ERROR, calculate_date_metrics
from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session import AgentSession, TeamSession, WorkflowSession

# ---------------------------------------------------------------------------
# In-memory GCS stub
# ---------------------------------------------------------------------------


class _FakeBlob:
    def __init__(self, bucket: "_FakeBucket", name: str) -> None:
        self._bucket = bucket
        self.name = name
        self.generation = None

    def download_as_bytes(self) -> bytes:
        from google.cloud.exceptions import NotFound  # type: ignore[import-untyped]

        if self.name not in self._bucket._objects:
            raise NotFound(self.name)
        data, self.generation = self._bucket._objects[self.name]
        return data.encode("utf-8")

    def upload_from_string(self, data: str, content_type: str = "application/json", if_generation_match=None) -> None:
        from google.cloud.exceptions import PreconditionFailed  # type: ignore[import-untyped]

        _, generation = self._bucket._objects.get(self.name, (None, 0))
        if if_generation_match is not None and if_generation_match != generation:
            raise PreconditionFailed(self.name)
        self._bucket._generation += 1
        self.generation = self._bucket._generation
        self._bucket._objects[self.name] = (data, self.generation)


class _FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self._objects: Dict[str, tuple] = {}
        self._generation = 0

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self, name)


class _FakeClient:
    _buckets: Dict[str, _FakeBucket] = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    def bucket(self, name: str) -> _FakeBucket:
        if name not in _FakeClient._buckets:
            _FakeClient._buckets[name] = _FakeBucket(name)
        return _FakeClient._buckets[name]


@pytest.fixture(autouse=True)
def _patch_gcs(monkeypatch):
    # Make sure agno.db.gcs_json.gcs_json_db.gcs.Client points to the fake.
    from agno.db.gcs_json import gcs_json_db as mod

    fake_gcs = types.SimpleNamespace(Client=_FakeClient)
    monkeypatch.setattr(mod, "gcs", fake_gcs)
    # Reset the buckets between tests so state doesn't leak.
    _FakeClient._buckets = {}
    yield


def _new_db(**kwargs):
    from agno.db.gcs_json.gcs_json_db import GcsJsonDb

    return GcsJsonDb(bucket_name="test-bucket", prefix="agno/", **kwargs)


_COMPLETED = RunStatus.completed.value


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(day: date) -> int:
    """Midday UTC of ``day``, so a session or run dated there lands in that UTC day."""
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _run_metrics(input_tokens, cache_read_tokens=0):
    return RunMetrics(
        input_tokens=input_tokens,
        output_tokens=10,
        total_tokens=input_tokens + 10,
        cache_read_tokens=cache_read_tokens,
    )


def _agent_run(run_id, created_at, input_tokens, status=RunStatus.completed, agent_id="agent-1", **kwargs):
    return RunOutput(
        run_id=run_id,
        agent_id=agent_id,
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(input_tokens, kwargs.pop("cache_read_tokens", 0)),
        created_at=created_at,
        **kwargs,
    )


def _persist(db, session, runs):
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _stored_rows(db, table_name):
    return {
        tuple(row[column] for column in ["aggregation_period", "date", "user_id"])
        + ((row["component_type"], row["component_id"]) if "component_type" in row else ()): row
        for row in db._read_metrics_file(table_name)
    }


def _everyone_row(db, day, period="daily"):
    return _stored_rows(db, db.aggregate_metrics_table_name)[(period, day, "")]


def _stored_sessions():
    db = _new_db()
    yesterday = _utc_date(1)
    _persist(
        db,
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=_noon_utc(yesterday)),
        [
            _agent_run("alice_run", _noon_utc(yesterday), 100),
            _agent_run("alice_error_run", _noon_utc(yesterday) + 60, 20, status=RunStatus.error),
        ],
    )
    _persist(
        db,
        AgentSession(session_id="bob_session", agent_id="agent-1", user_id="bob", created_at=_noon_utc(yesterday)),
        [_agent_run("bob_run", _noon_utc(yesterday) + 120, 200)],
    )
    _persist(
        db,
        AgentSession(session_id="alice_today", agent_id="agent-1", user_id="alice", created_at=_noon_utc(_utc_date(0))),
        [_agent_run("today_run", _noon_utc(_utc_date(0)), 1)],
    )
    return db


def _set_locked_at(db, locked_at):
    refresh_rows = db._read_json_file(db.metrics_refreshes_table_name)
    db._write_json_file(db.metrics_refreshes_table_name, [{**refresh_rows[0], "locked_at": locked_at}])


# A dataset of an agent, a team with a member and a workflow, two users and no user, over three days


def _build_dataset(db) -> List[Tuple[Any, Optional[str]]]:
    """Store the dataset, and return every stored run with its user."""
    old_day, yesterday, today = _utc_date(3), _utc_date(1), _utc_date(0)
    alice_runs = [
        _agent_run("alice_run", _noon_utc(old_day), 100, cache_read_tokens=7),
        _agent_run("alice_paused_run", _noon_utc(old_day) + 60, 50, status=RunStatus.paused),
    ]
    _persist(
        db,
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=_noon_utc(old_day)),
        alice_runs,
    )

    member_run = _agent_run("member_run", _noon_utc(yesterday) + 5, 20, agent_id="member-1", parent_run_id="team_run")
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(30, cache_read_tokens=3),
        member_responses=[member_run],
        created_at=_noon_utc(yesterday),
    )
    db.upsert_session(
        TeamSession(session_id="bob_session", team_id="team-1", user_id="bob", created_at=_noon_utc(yesterday))
    )
    db.upsert_run(team_run, session_id="bob_session", user_id="bob", run_index=0)
    db.upsert_run(member_run, session_id="bob_session", user_id="bob", run_index=1)

    workflow_run = WorkflowRunOutput(
        run_id="workflow_run", workflow_id="workflow-1", status=RunStatus.completed, created_at=_noon_utc(today)
    )
    _persist(
        db,
        WorkflowSession(session_id="workflow_session", workflow_id="workflow-1", created_at=_noon_utc(today)),
        [workflow_run],
    )
    return [(run, "alice") for run in alice_runs] + [
        (team_run, "bob"),
        (member_run, "bob"),
        (workflow_run, None),
    ]


def _ground_truth(runs: List[Tuple[Any, Optional[str]]]) -> Dict[Any, Dict[str, Any]]:
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


def _assert_matches_ground_truth(db, runs):
    aggregate_metrics_rows = _stored_rows(db, db.aggregate_metrics_table_name)
    for (day, user_id), counts in _ground_truth(runs).items():
        row = aggregate_metrics_rows[("daily", day, user_id)]
        assert {
            **{column: row[column] for column in counts if column != "cache_read_tokens"},
            "cache_read_tokens": row["token_details"].get("cache_read_tokens", 0),
        } == counts, (day, user_id)


def test_calculate_metrics_matches_a_direct_count_of_the_runs():
    """Ensure every day's aggregate metrics rows match a direct count of the stored runs"""
    db = _new_db()
    runs = _build_dataset(db)

    calculated = db.calculate_metrics()

    old_day, yesterday, today = _utc_date(3), _utc_date(1), _utc_date(0)
    assert {metric["date"] for metric in calculated} == {old_day, yesterday, today}
    _assert_matches_ground_truth(db, runs)
    aggregate_metrics_rows = _stored_rows(db, db.aggregate_metrics_table_name)
    assert aggregate_metrics_rows[("daily", old_day, "")]["agent_sessions_count"] == 1
    assert aggregate_metrics_rows[("daily", yesterday, "")]["team_sessions_count"] == 1
    assert aggregate_metrics_rows[("daily", today, "")]["workflow_sessions_count"] == 1
    assert (
        aggregate_metrics_rows[("daily", yesterday, "")]["users_count"],
        aggregate_metrics_rows[("daily", today, "")]["users_count"],
    ) == (1, 0)
    assert aggregate_metrics_rows[("daily", old_day, "")]["completed"] is True
    assert aggregate_metrics_rows[("daily", yesterday, "")]["completed"] is False

    # The member run is counted under the team that started it
    rows = _stored_rows(db, db.component_metrics_table_name)
    member_row = rows[("daily", yesterday, "bob", "agent", "member-1")]
    assert (member_row["parent_component_id"], member_row["root_component_id"]) == ("team-1", "team-1")

    # The runs with no user are read from their component rows
    metrics, _ = db.get_metrics(starting_date=today, ending_date=today, user_id="")
    assert [(metric["user_id"], metric["workflow_runs_count"]) for metric in metrics] == [(None, 1)]
    assert db.get_metrics_refresh_status()["status"] == "completed"


def test_calculate_metrics_rebuilds_a_reopened_day():
    """Ensure saving a run of a closed day reopens it, and the next calculation completes it again"""
    db = _new_db()
    runs = _build_dataset(db)
    db.calculate_metrics()
    old_day = _utc_date(3)
    version = _everyone_row(db, old_day)["version"]

    resumed_run = _agent_run("alice_paused_run", _noon_utc(old_day) + 60, 50)
    db.upsert_run(resumed_run, session_id="alice_session", user_id="alice")
    reopened_row = _everyone_row(db, old_day)
    assert (reopened_row["completed"], reopened_row["version"]) == (False, version + 1)

    calculated = db.calculate_metrics()
    assert old_day in {metric["date"] for metric in calculated}
    row = _everyone_row(db, old_day)
    assert row["completed"] is True
    assert row["status_metrics"] == {_COMPLETED: 2}
    _assert_matches_ground_truth(
        db, [(resumed_run, "alice") if run.run_id == "alice_paused_run" else (run, user) for run, user in runs]
    )


def test_session_save_reopens_the_day_the_session_is_stored_on():
    """Ensure a new session on a closed day reopens it, while saving the same session again does not"""
    db = _new_db()
    _build_dataset(db)
    db.calculate_metrics()
    old_day = _utc_date(3)
    version = _everyone_row(db, old_day)["version"]

    # Saving the same session again changes nothing it is counted under
    db.upsert_session(
        AgentSession(session_id="alice_session", agent_id="agent-1", user_id="alice", created_at=_noon_utc(old_day))
    )
    assert _everyone_row(db, old_day)["version"] == version

    db.upsert_session(
        AgentSession(session_id="late_session", agent_id="agent-1", user_id="carol", created_at=_noon_utc(old_day))
    )
    assert (_everyone_row(db, old_day)["completed"], _everyone_row(db, old_day)["version"]) == (False, version + 1)


def test_calculate_metrics_dates_releases_the_lock_when_stopped():
    """Ensure a stopped calculation writes the days it calculated and releases the lock"""
    db = _stored_sessions()
    calls = []

    def should_stop():
        calls.append(1)
        return len(calls) > 1

    assert db.calculate_metrics_dates(should_stop=should_stop) is None
    assert ("daily", _utc_date(1), "") in _stored_rows(db, db.aggregate_metrics_table_name)
    assert ("daily", _utc_date(0), "") not in _stored_rows(db, db.aggregate_metrics_table_name)
    assert db.get_metrics_refresh_status()["status"] == "failed"
    assert db.calculate_metrics() is not None


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column():
    """Ensure a run kept only in the legacy runs field is counted once, on its own day"""
    db = _new_db()
    session_day, run_day, yesterday = _utc_date(6), _utc_date(4), _utc_date(1)
    in_both = _agent_run("in_both", _noon_utc(yesterday), 10).to_dict()
    legacy_only = _agent_run("legacy_only", _noon_utc(yesterday), 20).to_dict()
    member_run = _agent_run("member_run", _noon_utc(yesterday) + 5, 20, agent_id="member-1", parent_run_id="team_run")
    team_run = TeamRunOutput(
        run_id="team_run",
        team_id="team-1",
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(30),
        member_responses=[member_run],
        created_at=_noon_utc(yesterday),
    )
    db.upsert_session(
        AgentSession(session_id="legacy", agent_id="agent-1", user_id="alice", created_at=_noon_utc(yesterday))
    )
    db.upsert_session(
        AgentSession(session_id="legacy_old", agent_id="agent-1", user_id="alice", created_at=_noon_utc(session_day))
    )
    db.upsert_session(
        TeamSession(session_id="legacy_team", team_id="team-1", user_id="bob", created_at=_noon_utc(yesterday))
    )
    legacy_runs = {
        "legacy": [in_both, legacy_only],
        "legacy_old": [_agent_run("legacy_run", _noon_utc(run_day), 20).to_dict()],
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
    assert _everyone_row(db, run_day)["agent_runs_count"] == 1
    alice_row = _stored_rows(db, db.component_metrics_table_name)[("daily", yesterday, "alice", "agent", "agent-1")]
    assert (alice_row["sessions_count"], alice_row["runs_count"], alice_row["input_tokens"]) == (1, 2, 30)
    # A legacy team member run is counted once
    bob_row = _stored_rows(db, db.aggregate_metrics_table_name)[("daily", yesterday, "bob")]
    assert (bob_row["team_runs_count"], bob_row["agent_runs_count"], bob_row["input_tokens"]) == (1, 1, 50)

    # Once the v3.0.0 migration is stamped, the legacy runs field is a backup only
    db.upsert_schema_version(db.session_table_name, "3.0.0")
    db.calculate_metrics(rebuild_from=yesterday)
    alice_row = _stored_rows(db, db.component_metrics_table_name)[("daily", yesterday, "alice", "agent", "agent-1")]
    assert (alice_row["runs_count"], alice_row["input_tokens"]) == (1, 10)


def test_a_aggregate_metrics_write_made_since_the_read_is_never_written_over(monkeypatch):
    """Ensure an aggregate metrics write made by another process since the read is never written over"""
    db = _new_db()
    _build_dataset(db)
    db.calculate_metrics()
    old_day = _utc_date(3)
    read_json_file_with_generation = db._read_json_file_with_generation
    reads = []

    def read_then_reopen(filename, create_table_if_not_found=False):
        result = read_json_file_with_generation(filename, create_table_if_not_found)
        if filename != db.aggregate_metrics_table_name:
            return result
        if not reads:
            # Another process reopens the day between the calculation's read of the aggregate metrics and its write
            _new_db().upsert_run(
                _agent_run("alice_paused_run", _noon_utc(old_day) + 60, 50), session_id="alice_session", user_id="alice"
            )
        reads.append(filename)
        return result

    def calculate_and_watch(*args):
        db._read_json_file_with_generation = read_then_reopen
        return calculate_date_metrics(*args)

    with monkeypatch.context() as patch:
        patch.setattr("agno.db.gcs_json.gcs_json_db.calculate_date_metrics", calculate_and_watch)
        db.calculate_metrics(rebuild_from=old_day)
    del db._read_json_file_with_generation

    # The write found the aggregate metrics written since its read, read them again and kept the reopen
    assert reads[:2] == [db.aggregate_metrics_table_name, db.aggregate_metrics_table_name]
    assert _everyone_row(db, old_day)["completed"] is False


def test_calculate_metrics_takes_over_a_lock_that_went_stale():
    """Ensure a held refresh blocks another calculation, and a stale one reads as failed and is taken over"""
    db = _stored_sessions()
    db._claim_metrics_refresh("stopped-worker")
    assert db.calculate_metrics() is None
    _set_locked_at(db, int(time.time()) - METRICS_LOCK_SECONDS)
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", METRICS_STOPPED_ERROR)

    assert db.calculate_metrics()
    assert db.get_metrics_refresh_status()["status"] == "completed"
    assert db._heartbeat_metrics_refresh("stopped-worker") is False
