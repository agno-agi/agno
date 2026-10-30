"""Tests for the OS metrics methods of ValkeyDb.

Uses a tiny in-memory stub for the GLIDE client so no real Valkey instance is
needed, as test_v3_valkey_migration_compat.py does.
"""

from __future__ import annotations

import fnmatch
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from agno.metrics import ModelMetrics, RunMetrics
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


class _RequestError(Exception):
    pass


class _ExpirySet:
    def __init__(self, expiry_type: Any = None, value: Any = None):
        self.value = value


class _ExpiryType:
    SEC = "SEC"


class _ConditionalChange:
    ONLY_IF_DOES_NOT_EXIST = "NX"


class _Batch:
    """Records commands; `_FakeGlideClient.exec` replays them."""

    def __init__(self, is_atomic: bool = False):
        self.commands: List[tuple] = []

    def get(self, key):
        self.commands.append(("get", key))

    def set(self, key, value, expiry=None):
        self.commands.append(("set", key, value))

    def delete(self, keys):
        self.commands.append(("delete", keys))

    def sadd(self, key, members):
        self.commands.append(("sadd", key, members))

    def srem(self, key, members):
        self.commands.append(("srem", key, members))

    def smembers(self, key):
        self.commands.append(("smembers", key))

    def zadd(self, key, members_scores):
        self.commands.append(("zadd", key, members_scores))

    def zrange(self, key, range_query, reverse=False):
        self.commands.append(("zrange", key, range_query, reverse))

    def hset(self, key, field_value_map):
        self.commands.append(("hset", key, field_value_map))

    def hincrby(self, key, field, amount):
        self.commands.append(("hincrby", key, field, amount))

    def hmget(self, key, fields):
        self.commands.append(("hmget", key, fields))

    def expire(self, key, seconds):
        self.commands.append(("expire", key, seconds))


class _FakeGlideClient:
    def __init__(self):
        self.strings: Dict[str, bytes] = {}
        self.sets: Dict[str, set] = {}
        self.zsets: Dict[str, Dict[str, float]] = {}
        self.hashes: Dict[str, Dict[str, bytes]] = {}
        # When each key with an expiry expires, by the clock the server reads
        self.expires_at: Dict[str, float] = {}
        self.clock = time.time

    def _kind(self, key: str) -> Optional[str]:
        if key in self.expires_at and self.expires_at[key] <= self.clock():
            self.delete([key])
        if key in self.strings:
            return "string"
        if key in self.sets:
            return "set"
        if key in self.zsets:
            return "zset"
        if key in self.hashes:
            return "hash"
        return None

    # -- strings --

    def get(self, key, buffer=None):
        if self._kind(key) in ("set", "zset", "hash"):
            raise _RequestError("WRONGTYPE Operation against a key holding the wrong kind of value")
        return self.strings.get(key)

    def set(self, key, value, conditional_set=None, expiry=None, **kwargs):
        if conditional_set is not None and self._kind(key) is not None:
            return None
        self.strings[key] = value.encode() if isinstance(value, str) else value
        if expiry is not None:
            self.expires_at[key] = self.clock() + expiry.value
        return "OK"

    def delete(self, keys):
        deleted = 0
        for key in keys:
            for store in (self.strings, self.sets, self.zsets, self.hashes):
                if key in store:
                    del store[key]
                    deleted += 1
            self.expires_at.pop(key, None)
        return deleted

    def scan(self, cursor="0", match=None, count=None):
        keys = list(self.strings) + list(self.sets) + list(self.zsets) + list(self.hashes)
        matched = [k.encode() for k in keys if match is None or fnmatch.fnmatch(k, match)]
        return [b"0", matched]

    # -- sets --

    def sadd(self, key, members):
        self.sets.setdefault(key, set()).update(members)
        return len(members)

    def srem(self, key, members):
        entries = self.sets.get(key, set())
        for member in members:
            entries.discard(member)
        return len(members)

    def smembers(self, key):
        return {m.encode() if isinstance(m, str) else m for m in self.sets.get(key, set())}

    # -- sorted sets --

    def zadd(self, key, members_scores, **kwargs):
        self.zsets.setdefault(key, {}).update(members_scores)
        return len(members_scores)

    def zrange(self, key, range_query, reverse=False):
        entries = self.zsets.get(key, {})
        ordered = sorted(entries.items(), key=lambda kv: (kv[1], kv[0]), reverse=reverse)
        return [m.encode() for m, _ in ordered]

    # -- hashes --

    def hset(self, key, field_value_map):
        entries = self.hashes.setdefault(key, {})
        for field, value in field_value_map.items():
            entries[field] = value.encode() if isinstance(value, str) else value
        return len(field_value_map)

    def hincrby(self, key, field, amount):
        entries = self.hashes.setdefault(key, {})
        entries[field] = str(int(entries.get(field, b"0")) + amount).encode()
        return int(entries[field])

    def hmget(self, key, fields):
        entries = self.hashes.get(key, {})
        return [entries.get(field) for field in fields]

    def expire(self, key, seconds, option=None):
        if self._kind(key) is None:
            return False
        self.expires_at[key] = self.clock() + seconds
        return True

    # -- transactions --

    def watch(self, keys):
        return "OK"

    def unwatch(self):
        return "OK"

    def exec(self, batch, raise_on_error=False):
        results: List[Any] = []
        for command in batch.commands:
            op = command[0]
            try:
                if op == "get":
                    results.append(self.get(command[1]))
                elif op == "set":
                    results.append(self.set(command[1], command[2]))
                elif op == "delete":
                    results.append(self.delete(command[1]))
                elif op == "sadd":
                    results.append(self.sadd(command[1], command[2]))
                elif op == "srem":
                    results.append(self.srem(command[1], command[2]))
                elif op == "smembers":
                    results.append(self.smembers(command[1]))
                elif op == "zadd":
                    results.append(self.zadd(command[1], command[2]))
                elif op == "zrange":
                    results.append(self.zrange(command[1], command[2], command[3]))
                elif op == "hset":
                    results.append(self.hset(command[1], command[2]))
                elif op == "hincrby":
                    results.append(self.hincrby(command[1], command[2], command[3]))
                elif op == "hmget":
                    results.append(self.hmget(command[1], command[2]))
                elif op == "expire":
                    results.append(self.expire(command[1], command[2]))
                else:
                    results.append(True)
            except _RequestError as exc:
                # GLIDE surfaces per-command failures as values, not raises
                results.append(exc)
        return results


@pytest.fixture()
def valkey_db(monkeypatch):
    """Create a ValkeyDb on the stub, with the GLIDE types patched to match."""
    import agno.db.valkey.valkey as valkey_module
    from agno.db.valkey.valkey import ValkeyDb

    monkeypatch.setattr(valkey_module, "RequestError", _RequestError)
    monkeypatch.setattr(valkey_module, "ExpirySet", _ExpirySet)
    monkeypatch.setattr(valkey_module, "ExpiryType", _ExpiryType)
    monkeypatch.setattr(valkey_module, "ConditionalChange", _ConditionalChange)
    client = _FakeGlideClient()
    db = ValkeyDb(valkey_client=client, db_prefix="agno")  # type: ignore[arg-type]
    db._create_pipeline = lambda: _Batch()  # type: ignore[method-assign]
    db._create_os_metrics_transaction = lambda: _Batch(is_atomic=True)  # type: ignore[method-assign]
    db._create_os_metrics_lock_transaction = lambda: _Batch(is_atomic=True)  # type: ignore[method-assign]
    db._exec_pipeline = lambda pipeline: client.exec(pipeline)  # type: ignore[method-assign]
    return db


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day an OS metrics record is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(day: date) -> int:
    """Midday UTC of the given day."""
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _persist(db, session_id: str, user_id: str, day: date, tokens: List[int]) -> None:
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


@pytest.fixture()
def seeded_db(valkey_db):
    """Two days back: one session of alice with two runs and one of bob with one run. Today: one of alice."""
    _persist(valkey_db, "alice_session", "alice", _utc_date(2), [100, 10])
    _persist(valkey_db, "bob_session", "bob", _utc_date(2), [200])
    _persist(valkey_db, "alice_session_today", "alice", _utc_date(0), [30])
    return valkey_db


def _later_clock(monkeypatch, seconds: int) -> None:
    """Move the clock the adapter reads forward, past the second the records were written in."""
    import agno.db.valkey.valkey as valkey_module

    later = time.time() + seconds
    monkeypatch.setattr(valkey_module, "time", SimpleNamespace(time=lambda: later, sleep=time.sleep))


def test_calculate_os_metrics_rows_and_totals(seeded_db):
    results = seeded_db.calculate_os_metrics()

    rows = {(row["date"], row["user_id"]): row for row in results}
    assert set(rows) == {(_utc_date(2), "alice"), (_utc_date(2), "bob"), (_utc_date(0), "alice")}
    assert rows[(_utc_date(2), "alice")]["sessions_count"] == 1
    assert rows[(_utc_date(2), "alice")]["runs_count"] == 2
    assert rows[(_utc_date(2), "alice")]["input_tokens"] == 110
    assert rows[(_utc_date(2), "alice")]["model_metrics"] == [
        {"model_id": "gpt-5", "model_provider": "OpenAI", "count": 2}
    ]

    totals = {record["date"]: record for record in seeded_db._get_all_os_metrics_totals_records()}
    # The day without traffic has a totals record of zeros
    assert sorted(totals) == [_utc_date(2), _utc_date(1), _utc_date(0)]
    assert totals[_utc_date(2)]["runs_count"] == 3
    assert totals[_utc_date(2)]["input_tokens"] == 310
    assert totals[_utc_date(1)]["sessions_count"] == 0
    # A day is completed one day after it ended
    assert [totals[_utc_date(day)]["completed"] for day in [2, 1, 0]] == [True, False, False]
    assert all(record["version"] == 1 for record in totals.values())


def test_get_os_metrics_every_owner_and_one_user(seeded_db):
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


def test_lazy_refresh_skipped_while_nothing_changed(seeded_db, monkeypatch):
    seeded_db.calculate_os_metrics()
    _later_clock(monkeypatch, 5)
    # The first lazy refresh rebuilds from yesterday on, the days the next one compares
    assert seeded_db._calculate_os_metrics(wait_for_rebuild=False) is not None
    assert seeded_db._calculate_os_metrics(wait_for_rebuild=False) is None

    _persist(seeded_db, "bob_session_today", "bob", _utc_date(0), [5])
    _later_clock(monkeypatch, 10)
    assert seeded_db._calculate_os_metrics(wait_for_rebuild=False) is not None


def test_lazy_refresh_skipped_while_another_process_rebuilds(seeded_db):
    seeded_db.valkey_client.set(seeded_db._os_metrics_lock_key(), "another-process")

    assert seeded_db._calculate_os_metrics(wait_for_rebuild=False) is None
    assert seeded_db._os_metrics_refreshed_at == 0.0


def test_versions_none_while_not_built(seeded_db):
    seeded_db._os_metrics_refreshed_at = time.time()
    assert seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) is None

    seeded_db.calculate_os_metrics()
    assert seeded_db.get_os_metrics_versions(_utc_date(2), _utc_date(0)) is not None


def test_month_rows_of_a_completed_month(valkey_db):
    month_start = (_utc_date(0).replace(day=1) - timedelta(days=1)).replace(day=1)
    if (_utc_date(0) - month_start).days < 40:
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    _persist(valkey_db, "alice_month_1", "alice", month_start, [100])
    _persist(valkey_db, "alice_month_2", "alice", month_start + timedelta(days=9), [50])
    _persist(valkey_db, "bob_month", "bob", month_start + timedelta(days=3), [20])

    valkey_db.calculate_os_metrics()

    month_totals = [
        record for record in valkey_db._get_all_os_metrics_totals_records() if record["aggregation_period"] == "monthly"
    ]
    assert [(record["date"], record["completed"], record["input_tokens"]) for record in month_totals] == [
        (month_start, True, 170)
    ]
    month_rows = [
        record
        for record in valkey_db._get_os_metrics_records(valkey_db._get_os_metrics_record_ids("user_id", ["alice"]))
        if record["aggregation_period"] == "monthly"
    ]
    assert [(record["date"], record["runs_count"], record["input_tokens"]) for record in month_rows] == [
        (month_start, 2, 150)
    ]

    totals, _ = valkey_db.get_os_metrics_totals(month_start, _utc_date(0), fields=["runs_count", "input_tokens"])
    assert totals == {"runs_count": 3, "input_tokens": 170}
    totals, _ = valkey_db.get_os_metrics_totals(month_start, _utc_date(0), user_id="alice", fields=["input_tokens"])
    assert totals == {"input_tokens": 150}


def test_first_build_reads_sessions_in_batches(valkey_db):
    for index in range(200):
        _persist(valkey_db, f"session_{index}", "alice", _utc_date(2), [10])
    # A request of more than 150 commands times out, as one read of every session of a large table does
    client = valkey_db.valkey_client

    def exec_pipeline(pipeline):
        if len(pipeline.commands) > 150:
            raise TimeoutError("timed out")
        return client.exec(pipeline)

    valkey_db._exec_pipeline = exec_pipeline  # type: ignore[method-assign]

    valkey_db.calculate_os_metrics()

    totals = {record["date"]: record for record in valkey_db._get_all_os_metrics_totals_records()}
    assert totals[_utc_date(2)]["sessions_count"] == 200


def _slow_day_reads(valkey_db, monkeypatch) -> List[bool]:
    """Make the nested run lookup and the rollup of a day take 40 s each, together longer than the lock, and let
    another rebuild try to take the lock during the rollup. Returns whether each try took it"""
    import agno.db.valkey.valkey as valkey_module

    clock = [time.time()]
    valkey_db.valkey_client.clock = lambda: clock[0]
    taken_over: List[bool] = []

    def slow(function, take_over: bool = False):
        def call(*args):
            clock[0] += 40
            if take_over:
                taken_over.append(valkey_db._lock_os_metrics(wait_for_rebuild=False) is not None)
            return function(*args)

        return call

    monkeypatch.setattr(valkey_module, "os_metrics_nested_run_ids", slow(valkey_module.os_metrics_nested_run_ids))
    monkeypatch.setattr(
        valkey_module, "calculate_date_os_metrics", slow(valkey_module.calculate_date_os_metrics, take_over=True)
    )
    return taken_over


def test_a_day_that_reads_for_longer_than_the_lock_keeps_it(valkey_db, monkeypatch):
    """The lock is renewed between the reads of a day, so a day that reads for longer than the lock is written"""
    # A parent run created before the days rebuilt, so each day reads it from the runs table, which renews the lock
    parent_run = RunOutput(run_id="parent_run", agent_id="agent-1", user_id="alice", created_at=_noon_utc(_utc_date(9)))
    valkey_db.upsert_run(parent_run, session_id="parent_session", user_id="alice", run_index=0)
    for days_ago in (1, 0):
        session_id = f"alice_session_{days_ago}"
        valkey_db.upsert_session(
            AgentSession(
                session_id=session_id,
                agent_id="agent-1",
                user_id="alice",
                created_at=_noon_utc(_utc_date(days_ago)),
                updated_at=_noon_utc(_utc_date(days_ago)),
            )
        )
        member_run = RunOutput(
            run_id=f"member_run_{days_ago}",
            agent_id="agent-1",
            user_id="alice",
            parent_run_id="parent_run",
            created_at=_noon_utc(_utc_date(days_ago)),
        )
        valkey_db.upsert_run(member_run, session_id=session_id, user_id="alice", run_index=0)
    taken_over = _slow_day_reads(valkey_db, monkeypatch)

    valkey_db.calculate_os_metrics()

    assert taken_over == [False, False]
    totals = valkey_db._get_all_os_metrics_totals_records()
    assert sorted(record["date"] for record in totals if record["aggregation_period"] == "daily") == [
        _utc_date(1),
        _utc_date(0),
    ]
