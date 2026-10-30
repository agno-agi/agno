"""Tests for the OS metrics methods of GcsJsonDb.

Uses a tiny in-memory stub for the GCS client/bucket/blob trio, keeping a
generation per object as GCS does, so no real GCS account is needed.
"""

from __future__ import annotations

import time
import types
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List

import pytest

from agno.metrics import RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession

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

    def delete(self, if_generation_match=None) -> None:
        from google.cloud.exceptions import NotFound, PreconditionFailed  # type: ignore[import-untyped]

        if self.name not in self._bucket._objects:
            raise NotFound(self.name)
        if if_generation_match is not None and if_generation_match != self._bucket._objects[self.name][1]:
            raise PreconditionFailed(self.name)
        del self._bucket._objects[self.name]


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


def _new_db():
    from agno.db.gcs_json.gcs_json_db import GcsJsonDb

    return GcsJsonDb(bucket_name="test-bucket", prefix="agno/")


def _utc_date(days_ago: int) -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _make_run(run_id: str, created_at: int, input_tokens: int, status: RunStatus = RunStatus.completed) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        status=status,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=RunMetrics(input_tokens=input_tokens, output_tokens=10, total_tokens=input_tokens + 10),
        created_at=created_at,
    )


def _insert_session(db, session_id: str, user_id: str, day: date, runs: List[RunOutput]) -> None:
    session = AgentSession(
        session_id=session_id, agent_id="agent-1", user_id=user_id, runs=runs, created_at=_noon_utc(day)
    )
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run=run, session_id=session_id, user_id=user_id, run_index=run_index)


def _insert_sessions(db) -> None:
    yesterday = _utc_date(1)
    _insert_session(
        db,
        "alice_session",
        "alice",
        yesterday,
        [
            _make_run("alice_run", _noon_utc(yesterday), 100),
            _make_run("alice_error_run", _noon_utc(yesterday) + 60, 20, status=RunStatus.error),
        ],
    )
    _insert_session(db, "bob_session", "bob", yesterday, [_make_run("bob_run", _noon_utc(yesterday) + 120, 200)])
    _insert_session(db, "alice_today", "alice", _utc_date(0), [_make_run("today_run", _noon_utc(_utc_date(0)), 1)])


def _rows_by_key(db, table_name: str) -> Dict[tuple, Dict]:
    return {(row["aggregation_period"], row["date"], row.get("user_id")): row for row in db._read_json_file(table_name)}


def test_calculate_os_metrics_writes_rows_and_totals():
    db = _new_db()
    _insert_sessions(db)

    db.calculate_os_metrics()

    yesterday = _utc_date(1).isoformat()
    today = _utc_date(0).isoformat()
    rows = _rows_by_key(db, db.os_metrics_table_name)
    assert set(rows) == {("daily", yesterday, "alice"), ("daily", yesterday, "bob"), ("daily", today, "alice")}
    alice_row = rows[("daily", yesterday, "alice")]
    assert (alice_row["component_type"], alice_row["component_id"], alice_row["parent_component_id"]) == (
        "agent",
        "agent-1",
        "",
    )
    assert alice_row["sessions_count"] == 1
    assert alice_row["runs_count"] == 2
    assert alice_row["status_metrics"] == {"COMPLETED": 1, "ERROR": 1}
    assert alice_row["input_tokens"] == 120

    totals = _rows_by_key(db, db.os_metrics_totals_table_name)
    assert set(totals) == {("daily", yesterday, None), ("daily", today, None)}
    assert totals[("daily", yesterday, None)]["runs_count"] == 3
    assert totals[("daily", yesterday, None)]["input_tokens"] == 320
    assert [row["version"] for row in totals.values()] == [1, 1]
    assert [row["completed"] for row in totals.values()] == [False, False]


def test_get_os_metrics_reads_every_owner_and_one_owner():
    db = _new_db()
    _insert_sessions(db)
    db.calculate_os_metrics()

    yesterday = _utc_date(1)
    today = _utc_date(0)
    metrics, updated_at = db.get_os_metrics(
        starting_date=yesterday, ending_date=today, fields=["runs_count", "status_metrics"]
    )
    assert metrics == [
        {"date": yesterday, "runs_count": 3, "status_metrics": {"COMPLETED": 2, "ERROR": 1}},
        {"date": today, "runs_count": 1, "status_metrics": {"COMPLETED": 1}},
    ]
    assert updated_at is not None

    metrics, _ = db.get_os_metrics(starting_date=yesterday, ending_date=today, user_id="bob")
    assert [(m["date"], m["runs_count"], m["input_tokens"]) for m in metrics] == [(yesterday, 1, 200)]

    totals, _ = db.get_os_metrics_totals(starting_date=yesterday, ending_date=today)
    assert (totals["runs_count"], totals["status_metrics"]) == (4, {"COMPLETED": 3, "ERROR": 1})


def test_refresh_os_metrics_reports_changes_and_moves_versions():
    db = _new_db()
    _insert_sessions(db)

    assert db.refresh_os_metrics()[2] is True
    versions = db.get_os_metrics_versions(_utc_date(1), _utc_date(0))
    assert versions == {f"daily {_utc_date(1).isoformat()}": 1, f"daily {_utc_date(0).isoformat()}": 1}

    _, _, changed = db.refresh_os_metrics()
    assert changed is False
    assert db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == versions

    db.upsert_run(
        run=_make_run("today_run_2", _noon_utc(_utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice"
    )
    _, _, changed = db.refresh_os_metrics()
    assert changed is True
    assert db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) == {
        f"daily {_utc_date(1).isoformat()}": 1,
        f"daily {_utc_date(0).isoformat()}": 2,
    }


def test_get_os_metrics_versions_is_none_while_incomplete():
    db = _new_db()
    _insert_sessions(db)
    # No lazy refresh before the read
    db._os_metrics_refreshed_at = time.time()

    assert db.get_os_metrics_versions(_utc_date(1), _utc_date(0)) is None


def test_lazy_refresh_with_nothing_new_is_skipped(monkeypatch):
    from agno.db.gcs_json import gcs_json_db as mod

    db = _new_db()
    _insert_sessions(db)
    # A clock past the second the sessions were written in, today's at noon, so the fingerprint is trusted
    later = max(time.time(), _noon_utc(_utc_date(0))) + 5
    monkeypatch.setattr(mod, "time", types.SimpleNamespace(time=lambda: later, sleep=time.sleep))

    assert db._calculate_os_metrics(wait_for_rebuild=True) is not None
    assert db._calculate_os_metrics(wait_for_rebuild=False) is None

    db.upsert_run(
        run=_make_run("today_run_2", _noon_utc(_utc_date(0)) + 60, 5), session_id="alice_today", user_id="alice"
    )
    assert db._calculate_os_metrics(wait_for_rebuild=False) is not None


def test_lazy_refresh_skips_while_another_rebuild_holds_the_lock():
    db = _new_db()
    _insert_sessions(db)
    lock_generation = db._lock_os_metrics(wait_for_rebuild=False)
    assert lock_generation is not None

    assert db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert db._os_metrics_refreshed_at == 0.0

    db._unlock_os_metrics(lock_generation)
    assert db._calculate_os_metrics(wait_for_rebuild=False) is not None


def test_completed_month_gets_month_rows():
    db = _new_db()
    month_start = (_utc_date(0).replace(day=1) - timedelta(days=32)).replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    _insert_session(db, "first_session", "alice", month_start, [_make_run("first_run", _noon_utc(month_start), 100)])
    _insert_session(db, "last_session", "alice", month_end, [_make_run("last_run", _noon_utc(month_end), 50)])

    db.calculate_os_metrics()

    month_row = _rows_by_key(db, db.os_metrics_table_name)[("monthly", month_start.isoformat(), "alice")]
    assert (month_row["sessions_count"], month_row["runs_count"], month_row["input_tokens"]) == (2, 2, 150)
    month_totals = _rows_by_key(db, db.os_metrics_totals_table_name)[("monthly", month_start.isoformat(), None)]
    assert (month_totals["runs_count"], month_totals["completed"], month_totals["version"]) == (2, True, 1)

    totals, _ = db.get_os_metrics_totals(starting_date=month_start, ending_date=month_end, user_id="alice")
    assert (totals["sessions_count"], totals["runs_count"], totals["input_tokens"]) == (2, 2, 150)
