"""Tests for the OS metrics methods of RedisDb.

Uses ``fakeredis`` so no real Redis instance is needed.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

fakeredis = pytest.importorskip("fakeredis")

from agno.db.redis.redis import RedisDb  # noqa: E402
from agno.db.redis.utils import generate_index_key  # noqa: E402
from agno.metrics import ModelMetrics, RunMetrics  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.session import AgentSession  # noqa: E402


@pytest.fixture()
def db() -> RedisDb:
    return RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True), db_prefix="agno")


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics record is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(day: date) -> int:
    """Midday UTC of the given day."""
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _persist(db: RedisDb, session_id: str, user_id: str, day: date, tokens: List[int]) -> None:
    """Store a session the way v3 does: the record, then each run in the runs table."""
    created_at = _noon_utc(day)
    runs = [
        RunOutput(
            run_id=f"{session_id}_run_{run_index}",
            agent_id="agent-1",
            user_id=user_id,
            status=RunStatus.completed,
            model="gpt-5",
            model_provider="OpenAI",
            metrics=RunMetrics(
                input_tokens=input_tokens,
                total_tokens=input_tokens,
                duration=1.5,
                details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI", input_tokens=input_tokens)]},
            ),
            created_at=created_at + run_index,
        )
        for run_index, input_tokens in enumerate(tokens)
    ]
    session = AgentSession(
        session_id=session_id, agent_id="agent-1", user_id=user_id, created_at=created_at, updated_at=created_at
    )
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run, session_id=session_id, user_id=user_id, run_index=run_index)


def _totals_records(db: RedisDb) -> List[Dict[str, Any]]:
    """Every stored OS metrics totals record, with its version."""
    return [
        db._get_os_metrics_totals_record(aggregation_period, day)
        for day, aggregation_period, _ in sorted(db._get_os_metrics_totals_days())
    ]


@pytest.fixture()
def seeded_db(db) -> RedisDb:
    """Two days back: one session of alice with two runs and one of bob with one run. Today: one of alice."""
    _persist(db, "alice_session", "alice", _utc_date(2), [100, 10])
    _persist(db, "bob_session", "bob", _utc_date(2), [200])
    _persist(db, "alice_session_today", "alice", _utc_date(0), [30])
    return db


def test_calculate_os_metrics_rows_and_totals(seeded_db):
    """A rebuild stores a record per user and agent per day, and a totals record for every day up to today."""
    results = seeded_db.calculate_os_metrics()

    rows = {(row["date"], row["user_id"]): row for row in results}
    assert set(rows) == {(_utc_date(2), "alice"), (_utc_date(2), "bob"), (_utc_date(0), "alice")}
    assert rows[(_utc_date(2), "alice")]["sessions_count"] == 1
    assert rows[(_utc_date(2), "alice")]["runs_count"] == 2
    assert rows[(_utc_date(2), "alice")]["input_tokens"] == 110
    assert rows[(_utc_date(2), "alice")]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}
    ]
    stored_rows = seeded_db._get_os_metrics_records_of_days([_utc_date(2)])
    assert sorted((row["user_id"], row["runs_count"]) for row in stored_rows) == [("alice", 2), ("bob", 1)]

    totals = {record["date"]: record for record in _totals_records(seeded_db)}
    # The day without traffic has a totals record of zeros
    assert sorted(totals) == [_utc_date(2), _utc_date(1), _utc_date(0)]
    assert totals[_utc_date(2)]["runs_count"] == 3
    assert totals[_utc_date(2)]["input_tokens"] == 310
    assert totals[_utc_date(1)]["sessions_count"] == 0
    # A day is completed one day after it ended
    assert [totals[_utc_date(day)]["completed"] for day in [2, 1, 0]] == [True, False, False]
    assert all(record["version"] == 1 for record in totals.values())


def test_get_os_metrics_every_owner_and_one_user(seeded_db):
    """A read returns each day's totals for every owner, or one user's, with only the fields asked for."""
    seeded_db.calculate_os_metrics()

    days, latest_updated_at = seeded_db.get_os_metrics(_utc_date(2), _utc_date(0), fields=["runs_count"])
    assert latest_updated_at is not None
    assert days == [
        {"date": _utc_date(2), "runs_count": 3},
        {"date": _utc_date(1), "runs_count": 0},
        {"date": _utc_date(0), "runs_count": 1},
    ]

    days, _ = seeded_db.get_os_metrics(_utc_date(2), _utc_date(0), user_id="bob", fields=["input_tokens"])
    assert days == [{"date": _utc_date(2), "input_tokens": 200}]

    totals, _ = seeded_db.get_os_metrics_totals(_utc_date(2), _utc_date(0), fields=["sessions_count", "runs_count"])
    assert totals == {"sessions_count": 3, "runs_count": 4}


def test_versions_move_only_when_a_day_changes(seeded_db):
    """A rebuild with nothing new keeps every version; one more run moves the version of its day only."""
    assert seeded_db.refresh_os_metrics()[2] is True
    versions = seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0))
    assert set(versions) == {f"daily {_utc_date(day).isoformat()}" for day in [2, 1, 0]}

    previous_updated_at, latest_updated_at, changed = seeded_db.refresh_os_metrics()
    assert (previous_updated_at == latest_updated_at, changed) == (True, False)
    assert seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) == versions

    _persist(seeded_db, "bob_session_today", "bob", _utc_date(0), [5])
    assert seeded_db.refresh_os_metrics()[2] is True
    new_versions = seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0))
    assert new_versions[f"daily {_utc_date(0).isoformat()}"] == 2
    assert new_versions[f"daily {_utc_date(2).isoformat()}"] == 1


def test_lazy_refresh_rebuilds_without_a_fingerprint(seeded_db):
    """Sessions and runs have no index by date, so every lazy refresh rebuilds, and one with nothing new writes
    nothing."""
    seeded_db.calculate_os_metrics()
    versions = seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0))

    _, written_totals_rows = seeded_db._calculate_os_metrics(wait_for_rebuild=False)
    assert written_totals_rows == []
    assert seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) == versions


def test_lazy_refresh_skipped_while_another_process_rebuilds(seeded_db):
    """A lazy refresh does not wait for the lock another process holds, and the next read tries again."""
    seeded_db.redis_client.set(seeded_db._os_metrics_lock_key(), "another-process")

    assert seeded_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert seeded_db._os_metrics_refreshed_at == 0.0


def test_versions_none_while_not_built(seeded_db):
    """A database with sessions and no totals record for yesterday is reported as still being built."""
    seeded_db._os_metrics_refreshed_at = time.time()
    assert seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) is None

    seeded_db.calculate_os_metrics()
    assert seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) is not None


def test_month_rows_of_a_completed_month(db):
    """A completed month gets its month records and a completed month totals record, which a long read uses."""
    month_start = (_utc_date(0).replace(day=1) - timedelta(days=1)).replace(day=1)
    if (_utc_date(0) - month_start).days < 40:
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    _persist(db, "alice_month_1", "alice", month_start, [100])
    _persist(db, "alice_month_2", "alice", month_start + timedelta(days=9), [50])
    _persist(db, "bob_month", "bob", month_start + timedelta(days=3), [20])

    db.calculate_os_metrics()

    month_totals = [record for record in _totals_records(db) if record["aggregation_period"] == "monthly"]
    assert [(record["date"], record["completed"], record["input_tokens"]) for record in month_totals] == [
        (month_start, True, 170)
    ]
    alice_record_ids = list(db.redis_client.smembers(generate_index_key("agno", "os_metrics", "user_id", "alice")))
    month_rows = [
        record for record in db._get_os_metrics_records(alice_record_ids) if record["aggregation_period"] == "monthly"
    ]
    assert [(record["date"], record["runs_count"], record["input_tokens"]) for record in month_rows] == [
        (month_start, 2, 150)
    ]

    totals, _ = db.get_os_metrics_totals(month_start, _utc_date(0), fields=["runs_count", "input_tokens"])
    assert totals == {"runs_count": 3, "input_tokens": 170}
    totals, _ = db.get_os_metrics_totals(month_start, _utc_date(0), user_id="alice", fields=["input_tokens"])
    assert totals == {"input_tokens": 150}


def test_lock_renewed_while_a_day_is_read(db, monkeypatch: pytest.MonkeyPatch):
    """A day whose reads outlast the lock is still written, as every read batch renews the lock."""
    import agno.db.redis.redis as redis_module

    _persist(db, "alice_session", "alice", _utc_date(2), [100])
    monkeypatch.setattr(redis_module, "OS_METRICS_LOCK_MILLISECONDS", 300)
    monkeypatch.setattr(redis_module, "OS_METRICS_BATCH_SIZE", 1)
    # Four slow lookups of nested runs, 0.6 s in all, twice the lock
    monkeypatch.setattr(redis_module, "os_metrics_nested_run_ids", lambda runs: {f"nested_{i}" for i in range(4)})
    generate_redis_key = redis_module.generate_redis_key

    def slow_generate_redis_key(prefix: str, table_type: str, key_id: str) -> str:
        if key_id.startswith("nested_"):
            time.sleep(0.15)
        return generate_redis_key(prefix=prefix, table_type=table_type, key_id=key_id)

    monkeypatch.setattr(redis_module, "generate_redis_key", slow_generate_redis_key)

    _, written_totals_rows = db._calculate_os_metrics(wait_for_rebuild=False)
    assert [record["date"] for record in written_totals_rows] == [_utc_date(2), _utc_date(1), _utc_date(0)]
