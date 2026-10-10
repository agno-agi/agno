"""Unit tests for the OS Metrics related methods of the RedisDb class"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

fakeredis = pytest.importorskip("fakeredis")

from agno.db.redis.redis import RedisDb  # noqa: E402
from agno.db.redis.utils import deserialize_os_metrics_record  # noqa: E402
from agno.metrics import ModelMetrics, RunMetrics  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.session.agent import AgentSession  # noqa: E402


def _new_db() -> RedisDb:
    return RedisDb(redis_client=fakeredis.FakeRedis(decode_responses=True), db_prefix="agno")


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back"""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics record is keyed by"""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _persist(db: RedisDb, session) -> None:
    """Store a session the way v3 does: the record, then each run in the runs table"""
    db.upsert_session(session)
    for run_index, run in enumerate(session.runs or []):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _run_metrics(input_tokens: int, output_tokens: int) -> RunMetrics:
    """The metrics a finished run carries: tokens, and the model that served it"""
    tokens: Dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    return RunMetrics(**tokens, details={"model": [ModelMetrics(id="gpt-5", provider="OpenAI", **tokens)]})


def _make_run(run_id: str, user_id: str, created_at: int, input_tokens: int, output_tokens: int) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        user_id=user_id,
        status=RunStatus.completed,
        model="gpt-5",
        model_provider="OpenAI",
        metrics=_run_metrics(input_tokens, output_tokens),
        created_at=created_at,
    )


def _make_session(session_id: str, user_id: str, days_ago: int, runs: list) -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id="agent-1",
        user_id=user_id,
        runs=runs,
        created_at=_noon_utc(days_ago),
        updated_at=_noon_utc(days_ago),
    )


def _stored_rows(db: RedisDb) -> Dict[tuple, Dict]:
    """Every OS metrics record stored for one owner, keyed by (date, user_id), without the state key"""
    rows = [
        deserialize_os_metrics_record(record)
        for record in db._get_all_records("os_metrics")
        if record.get("aggregation_period") == "daily"
    ]
    return {(row["date"], row["user_id"]): row for row in rows}


@pytest.fixture
def sample_sessions_for_os_metrics() -> List[AgentSession]:
    """Fixture returning the sessions of two days back, one of alice and one of bob, plus one of alice today"""
    past_day, today = _noon_utc(2), _noon_utc(0)
    alice_runs = [
        _make_run("alice_run_1", "alice", past_day, 100, 50),
        _make_run("alice_run_2", "alice", past_day + 60, 10, 5),
    ]
    return [
        _make_session("alice_session", "alice", 2, alice_runs),
        _make_session("bob_session", "bob", 2, [_make_run("bob_run_1", "bob", past_day, 200, 100)]),
        _make_session("alice_session_today", "alice", 0, [_make_run("alice_run_today", "alice", today, 30, 20)]),
    ]


@pytest.fixture
def db(sample_sessions_for_os_metrics) -> RedisDb:
    """Fixture returning a database holding the sample sessions and their runs"""
    db = _new_db()
    for session in sample_sessions_for_os_metrics:
        _persist(db, session)
    return db


def test_calculate_os_metrics(db):
    """Ensure a rebuild stores the records of a day with the sessions, runs and tokens of each owner"""
    assert db.calculate_os_metrics()

    rows = _stored_rows(db)
    assert set(rows) == {(_utc_date(2), "alice"), (_utc_date(2), "bob"), (_utc_date(0), "alice")}

    alice_row = rows[(_utc_date(2), "alice")]
    assert alice_row["sessions_count"] == 1
    assert alice_row["runs_count"] == 2
    assert alice_row["token_metrics"]["input_tokens"] == 110
    assert alice_row["token_metrics"]["output_tokens"] == 55
    assert alice_row["token_metrics"]["total_tokens"] == 165

    bob_row = rows[(_utc_date(2), "bob")]
    assert bob_row["runs_count"] == 1
    assert bob_row["token_metrics"]["total_tokens"] == 300


def test_get_os_metrics_by_date(db):
    """Ensure a read returns the totals of each day of a date range, with only the fields asked for"""
    db.calculate_os_metrics()

    totals, latest_updated_at = db.get_os_metrics(_utc_date(2), _utc_date(0))
    assert latest_updated_at is not None
    assert [total["date"] for total in totals] == [_utc_date(2), _utc_date(0)]
    assert [total["sessions_count"] for total in totals] == [2, 1]
    assert [total["runs_count"] for total in totals] == [3, 1]
    assert [total["token_metrics"]["total_tokens"] for total in totals] == [465, 50]

    totals, _ = db.get_os_metrics(_utc_date(2), _utc_date(2), fields=["runs_count"])
    assert totals == [{"date": _utc_date(2), "runs_count": 3}]


def test_get_os_metrics_by_user(db):
    """Ensure a read for one user returns only the numbers of that user"""
    db.calculate_os_metrics()

    totals, _ = db.get_os_metrics(_utc_date(2), _utc_date(0), user_id="bob")
    assert [total["date"] for total in totals] == [_utc_date(2)]
    assert totals[0]["sessions_count"] == 1
    assert totals[0]["runs_count"] == 1
    assert totals[0]["token_metrics"]["total_tokens"] == 300


def test_calculate_os_metrics_after_new_run(db):
    """Ensure a rebuild after one more run changes the stored numbers, and a rebuild with nothing new does not"""
    db.calculate_os_metrics()
    assert _stored_rows(db)[(_utc_date(0), "alice")]["runs_count"] == 1

    new_run = _make_run("alice_run_today_2", "alice", _noon_utc(0) + 60, 5, 5)
    db.upsert_run(new_run, session_id="alice_session_today", user_id="alice", run_index=1)
    db.calculate_os_metrics()

    rows = _stored_rows(db)
    assert rows[(_utc_date(0), "alice")]["runs_count"] == 2
    assert rows[(_utc_date(0), "alice")]["token_metrics"]["total_tokens"] == 60

    db.calculate_os_metrics()
    assert _stored_rows(db) == rows


def test_refresh_os_metrics(db):
    """Ensure a refresh reports when the records were last updated before and after it, and whether any changed"""
    before, after, changed = db.refresh_os_metrics()
    assert before is None and after is not None and changed is True

    assert db.refresh_os_metrics() == (after, after, False)


def test_get_os_metrics_totals_and_state(db):
    """Ensure the totals of a whole date range are returned, and the state the records are in"""
    db.calculate_os_metrics()

    totals, latest_updated_at = db.get_os_metrics_totals(_utc_date(2), _utc_date(0))
    assert totals["sessions_count"] == 3
    assert totals["runs_count"] == 4
    assert totals["token_metrics"]["total_tokens"] == 515

    updated_at, state_hash = db.get_os_metrics_state()
    assert updated_at == latest_updated_at
    assert state_hash

    # Records that expire change without a rebuild, so no state is reported for them
    db.expire = 60
    assert db.get_os_metrics_state() == (None, "")
