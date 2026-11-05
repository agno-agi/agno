"""Tests for the component metrics methods of ValkeyDb.

Uses a tiny in-memory stub for the GLIDE client so no real Valkey instance is
needed, as test_v3_valkey_migration_compat.py does.
"""

from __future__ import annotations

import fnmatch
import json
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest

from agno.db.utils import METRICS_LOCK_SECONDS
from agno.db.valkey.utils import generate_valkey_key, metrics_record_key, serialize_data
from agno.db.valkey.valkey import ValkeyDb
from agno.session import AgentSession, TeamSession, WorkflowSession

# ---------------------------------------------------------------------------
# In-memory GLIDE client stub
#
# Backed by one dict per Valkey type. Values come back as bytes, as GLIDE returns
# them.
# ---------------------------------------------------------------------------


class _RequestError(Exception):
    pass


class _ExpirySet:
    def __init__(self, expiry_type: Any = None, value: Any = None):
        self.value = value


class _ExpiryType:
    SEC = "SEC"


class _InfBound:
    POS_INF = "+inf"
    NEG_INF = "-inf"


class _ScoreBoundary:
    def __init__(self, value: float, is_inclusive: bool = True):
        self.value = value
        self.is_inclusive = is_inclusive


class _Limit:
    def __init__(self, offset: int, count: int):
        self.offset = offset
        self.count = count


class _RangeByScore:
    def __init__(self, start: Any, end: Any, limit: Optional[_Limit] = None):
        self.start = start
        self.end = end
        self.limit = limit


class _RangeByIndex:
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end


class _Batch:
    """Records commands; `_FakeGlideClient.exec` replays them."""

    def __init__(self, is_atomic: bool = False):
        self.is_atomic = is_atomic
        self.commands: List[Tuple[str, tuple]] = []

    def __getattr__(self, name: str):
        def record(*args, **kwargs):
            self.commands.append((name, args))
            return self

        return record


def _encode(value: Any) -> bytes:
    return value.encode() if isinstance(value, str) else value


def _cjson_number(value: str) -> Any:
    # The scripts decode and encode the row of the metrics refreshes table with cjson, which keeps 14 digits
    return json.loads("%.14g" % int(value))


def _in_range(score: float, start: Any, end: Any) -> bool:
    above = start == _InfBound.NEG_INF or (score >= start.value if start.is_inclusive else score > start.value)
    below = end == _InfBound.POS_INF or (score <= end.value if end.is_inclusive else score < end.value)
    return above and below


class _FakeGlideClient:
    def __init__(self):
        self.strings: Dict[str, bytes] = {}
        self.sets: Dict[str, set] = {}
        self.zsets: Dict[str, Dict[str, float]] = {}
        self.hashes: Dict[str, Dict[str, bytes]] = {}

    # -- strings --

    def get(self, key, buffer=None):
        return self.strings.get(key)

    def set(self, key, value, conditional_set=None, expiry=None, **kwargs):
        self.strings[key] = _encode(value)
        return "OK"

    def delete(self, keys):
        deleted = 0
        for key in keys:
            for store in (self.strings, self.sets, self.zsets, self.hashes):
                if key in store:
                    del store[key]
                    deleted += 1
        return deleted

    def exists(self, keys):
        return sum(1 for key in keys for store in (self.strings, self.sets, self.zsets, self.hashes) if key in store)

    def scan(self, cursor="0", match=None, count=None):
        keys = list(self.strings) + list(self.sets) + list(self.zsets) + list(self.hashes)
        return [b"0", [key.encode() for key in keys if match is None or fnmatch.fnmatch(key, match)]]

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
        return {_encode(member) for member in self.sets.get(key, set())}

    # -- sorted sets --

    def zadd(self, key, members_scores, **kwargs):
        self.zsets.setdefault(key, {}).update(members_scores)
        return len(members_scores)

    def zrem(self, key, members):
        entries = self.zsets.get(key, {})
        for member in members:
            entries.pop(member, None)
        return len(members)

    def zrange_withscores(self, key, range_query, reverse=False):
        ordered = sorted(self.zsets.get(key, {}).items(), key=lambda entry: (entry[1], entry[0]))
        if isinstance(range_query, _RangeByIndex):
            end = len(ordered) if range_query.end == -1 else range_query.end + 1
            ordered = ordered[range_query.start : end]
        else:
            ordered = [entry for entry in ordered if _in_range(entry[1], range_query.start, range_query.end)]
            if range_query.limit is not None:
                ordered = ordered[range_query.limit.offset : range_query.limit.offset + range_query.limit.count]
        return {member.encode(): score for member, score in ordered}

    def zrange(self, key, range_query, reverse=False):
        return list(self.zrange_withscores(key, range_query, reverse))

    # -- hashes --

    def hset(self, key, field_value_map):
        self.hashes.setdefault(key, {}).update({field: _encode(value) for field, value in field_value_map.items()})
        return len(field_value_map)

    def hsetnx(self, key, field, value):
        entries = self.hashes.setdefault(key, {})
        if field in entries:
            return False
        entries[field] = _encode(value)
        return True

    def hincrby(self, key, field, amount):
        entries = self.hashes.setdefault(key, {})
        entries[field] = str(int(entries.get(field, b"0")) + amount).encode()
        return int(entries[field])

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hmget(self, key, fields):
        entries = self.hashes.get(key, {})
        return [entries.get(field) for field in fields]

    def hgetall(self, key):
        return {field.encode(): value for field, value in self.hashes.get(key, {}).items()}

    def hkeys(self, key):
        return [field.encode() for field in self.hashes.get(key, {})]

    def hdel(self, key, fields):
        entries = self.hashes.get(key, {})
        return sum(1 for field in fields if entries.pop(field, None) is not None)

    def expire(self, key, seconds, option=None):
        return True

    def time(self):
        return [str(int(time.time())).encode(), b"0"]

    # -- scripts, run as the Lua of agno.db.valkey.utils runs them --

    def _holds(self, refresh_key: str, worker_id: str) -> bool:
        stored = self.strings.get(refresh_key)
        return stored is not None and json.loads(stored)["locked_by"] == (worker_id or None)

    def _claim(self, keys, args):
        now = int(time.time())
        stored = self.strings.get(keys[0])
        row = {"id": args[1], "finished_at": None, "fingerprint": None}
        if stored is not None:
            row = json.loads(stored)
            if row["locked_by"] is not None and row["locked_at"] > now - int(args[2]):
                return None
        row.update(locked_by=args[0], locked_at=now, started_at=now, status="running", error=None)
        self.strings[keys[0]] = json.dumps(row).encode()
        return self.strings[keys[0]]

    def _heartbeat(self, keys, args):
        if not self._holds(keys[0], args[0]):
            return 0
        self.strings[keys[0]] = json.dumps(
            {**json.loads(self.strings[keys[0]]), "locked_at": int(time.time())}
        ).encode()
        return 1

    def _release(self, keys, args):
        if not self._holds(keys[0], args[0]):
            return 0
        row = {**json.loads(self.strings[keys[0]]), "locked_by": None, "locked_at": None}
        if args[1] == "stopped":
            finished = row["finished_at"] is not None
            row.update(status="completed" if finished else "failed", error=None if finished else args[3])
        elif args[1] == "completed":
            stored_fingerprint = row["fingerprint"]
            row.update(
                status="completed",
                error=None,
                finished_at=int(time.time()),
                fingerprint=json.loads(args[2], parse_int=_cjson_number),
            )
            if stored_fingerprint != json.loads(args[4]):
                row["fingerprint"] = stored_fingerprint
        else:
            row.update(status="failed", error=args[3])
        self.strings[keys[0]] = json.dumps(row).encode()
        return 1

    def _fenced_writes(self, keys, args):
        if not self._holds(keys[0], args[0]):
            return 0
        for name, key_index, *rest in json.loads(args[1]):
            key = keys[key_index - 1]
            if name == "SET":
                self.set(key, rest[0])
            elif name == "DEL":
                self.delete([key])
            elif name == "SADD":
                self.sadd(key, rest)
            elif name == "SREM":
                self.srem(key, rest)
            elif name == "HSET":
                self.hset(key, dict(zip(rest[::2], rest[1::2])))
            elif name == "HSETNX":
                self.hsetnx(key, *rest)
            elif name == "HINCRBY":
                self.hincrby(key, *rest)
        return 1

    def _upsert_aggregate_metrics_row(self, keys, args):
        if not self._holds(keys[0], args[0]):
            return 0
        fields = json.loads(args[2])
        version = self.hget(keys[1], "version")
        if version is not None:
            if args[1] == "" or int(version) != int(args[1]):
                fields["completed"] = "false"
            created_at = self.hget(keys[1], "created_at")
            if created_at is not None:
                fields["created_at"] = created_at.decode()
            fields["version"] = str(int(version) + 1)
        else:
            fields["version"] = "1"
        self.hset(keys[1], fields)
        self.sadd(keys[2], [args[4]])
        self.sadd(keys[3], [args[4]])
        return 1

    def invoke_script(self, script, keys=None, args=None):
        import agno.db.valkey.utils as valkey_utils

        run = {
            valkey_utils._CLAIM_METRICS_REFRESH_SCRIPT: self._claim,
            valkey_utils._HEARTBEAT_METRICS_REFRESH_SCRIPT: self._heartbeat,
            valkey_utils._RELEASE_METRICS_REFRESH_SCRIPT: self._release,
            valkey_utils._FENCED_METRICS_WRITES_SCRIPT: self._fenced_writes,
            valkey_utils._UPSERT_AGGREGATE_METRICS_ROW_SCRIPT: self._upsert_aggregate_metrics_row,
        }[script]
        return run(keys or [], args or [])

    def exec(self, batch, raise_on_error=False):
        if not batch.commands:
            raise _RequestError("Received empty pipeline")
        results: List[Any] = []
        for name, args in batch.commands:
            try:
                results.append(getattr(self, name)(*args))
            except Exception as exc:
                if raise_on_error:
                    raise _RequestError(str(exc))
                # GLIDE surfaces per-command failures as values, not raises
                results.append(_RequestError(str(exc)))
        return results


@pytest.fixture()
def db(monkeypatch) -> ValkeyDb:
    """A ValkeyDb on the stub, with the GLIDE types patched to match."""
    import agno.db.valkey.valkey as valkey_module

    monkeypatch.setattr(valkey_module, "Batch", _Batch)
    monkeypatch.setattr(valkey_module, "ExpirySet", _ExpirySet)
    monkeypatch.setattr(valkey_module, "ExpiryType", _ExpiryType)
    monkeypatch.setattr(valkey_module, "GlideClient", _FakeGlideClient)
    monkeypatch.setattr(valkey_module, "RequestError", _RequestError)
    monkeypatch.setattr(valkey_module, "RangeByIndex", _RangeByIndex)
    monkeypatch.setattr(valkey_module, "RangeByScore", _RangeByScore)
    monkeypatch.setattr(valkey_module, "ScoreBoundary", _ScoreBoundary)
    monkeypatch.setattr(valkey_module, "InfBound", _InfBound)
    monkeypatch.setattr(valkey_module, "Limit", _Limit)
    return ValkeyDb(valkey_client=_FakeGlideClient(), db_prefix="agno")  # type: ignore[arg-type]


def _utc_date(days_ago: int) -> date:
    """The UTC day ``days_ago`` days back, the day a component metrics row is keyed by."""
    return datetime.now(timezone.utc).date() - timedelta(days=days_ago)


def _noon_utc(days_ago: int) -> int:
    """Midday UTC, ``days_ago`` days back."""
    day = _utc_date(days_ago)
    return int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())


def _run(
    run_id: str,
    created_at: int,
    input_tokens: int,
    agent_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    parent_run_id: Optional[str] = None,
    status: str = "COMPLETED",
    member_responses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """A stored run: tokens, cache tokens and the model that served it."""
    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "team_id": team_id,
        "workflow_id": workflow_id,
        "parent_run_id": parent_run_id,
        "status": status,
        "model": "gpt-5.6-luna",
        "model_provider": "OpenAI",
        "metrics": {
            "input_tokens": input_tokens,
            "output_tokens": input_tokens // 2,
            "total_tokens": input_tokens + input_tokens // 2,
            "cache_read_tokens": input_tokens // 10,
            "details": {"model": [{"id": "gpt-5.6-luna", "provider": "OpenAI", "input_tokens": input_tokens}]},
        },
        "member_responses": member_responses or [],
        "created_at": created_at,
    }


def _save(db: ValkeyDb, session: Any, runs: List[Dict[str, Any]]) -> None:
    """Store a session the way v3 does: the record, then each run in the runs table."""
    db.upsert_session(session)
    for run_index, run in enumerate(runs):
        db.upsert_run(run, session_id=session.session_id, user_id=session.user_id, run_index=run_index)


def _seed(db: ValkeyDb) -> None:
    """Three days: an agent of alice, a team of bob with a member and a paused run, a workflow with no user, three
    days back; an agent of bob two days back; a team of alice today."""
    day3 = _noon_utc(3)
    _save(
        db,
        AgentSession(session_id="s-agent", agent_id="agent-1", user_id="alice", created_at=day3),
        [_run("r-agent-1", day3, 100, agent_id="agent-1"), _run("r-agent-2", day3 + 1, 200, agent_id="agent-1")],
    )
    member_run = _run("r-member", day3 + 3, 40, agent_id="member-1", parent_run_id="r-team")
    _save(
        db,
        TeamSession(session_id="s-team", team_id="team-1", user_id="bob", created_at=day3 + 2),
        [
            _run("r-team", day3 + 2, 60, team_id="team-1", member_responses=[member_run]),
            member_run,
            _run("r-paused", day3 + 4, 5, team_id="team-1", status="PAUSED"),
        ],
    )
    _save(
        db,
        WorkflowSession(session_id="s-workflow", workflow_id="workflow-1", created_at=day3 + 5),
        [_run("r-workflow", day3 + 5, 30, workflow_id="workflow-1")],
    )
    day2 = _noon_utc(2)
    _save(
        db,
        AgentSession(session_id="s-agent-bob", agent_id="agent-1", user_id="bob", created_at=day2),
        [_run("r-agent-bob", day2, 70, agent_id="agent-1")],
    )
    today = _noon_utc(0) if datetime.now(timezone.utc).hour >= 12 else int(time.time()) - 60
    _save(
        db,
        TeamSession(session_id="s-team-today", team_id="team-1", user_id="alice", created_at=today),
        [_run("r-team-today", today, 10, team_id="team-1")],
    )


def _backdate(db: ValkeyDb) -> None:
    """Date every update of the sessions and runs to a minute ago, so none was updated in the current second."""
    for table_type in ["sessions", "runs"]:
        key_prefix = generate_valkey_key("agno", table_type, "")
        for key, data in list(db.valkey_client.strings.items()):
            if key.startswith(key_prefix):
                record = json.loads(data)
                db.valkey_client.set(key, serialize_data({**record, "updated_at": int(time.time()) - 60}))


def _versions(db: ValkeyDb, starting_date: date, ending_date: date) -> Dict[str, int]:
    """The version of every everyone row of a day or a month in the date range, keyed by its period and date."""
    record_ids = [
        record_id
        for record_id in db._get_metrics_everyone_record_ids()
        if starting_date <= metrics_record_key(record_id)[0] <= ending_date
    ]
    return {
        f"{row['aggregation_period']} {row['date'].isoformat()}": row["version"]
        for row in db._get_aggregate_metrics_records(record_ids)
    }


def _ground_truth(db: ValkeyDb) -> Dict[Tuple[date, str], Dict[str, int]]:
    """Count the stored sessions and runs directly, per day and user: "*" for every user, "" for no user."""
    truth: Dict[Tuple[date, str], Dict[str, int]] = {}

    def bucket(created_at: int, user_id: str) -> List[Dict[str, int]]:
        day = datetime.fromtimestamp(created_at, tz=timezone.utc).date()
        return [truth.setdefault((day, key), {}) for key in ["*", user_id]]

    for session in db._get_all_records("sessions"):
        for counts in bucket(session["created_at"], session.get("user_id") or ""):
            key = f"{session['session_type']}_sessions_count"
            counts[key] = counts.get(key, 0) + 1
    for run in db._get_all_records("runs"):
        metrics = run["run_data"]["metrics"]
        for counts in bucket(run["created_at"], run.get("user_id") or ""):
            for key, value in [
                (f"{run['run_type']}_runs_count", 1),
                ("root_runs_count", 0 if run.get("parent_run_id") else 1),
                ("input_tokens", metrics["input_tokens"]),
                ("output_tokens", metrics["output_tokens"]),
                ("total_tokens", metrics["total_tokens"]),
                ("cache_read_tokens", metrics["cache_read_tokens"]),
            ]:
                counts[key] = counts.get(key, 0) + value
    return truth


_COUNTS = [
    "agent_sessions_count",
    "team_sessions_count",
    "workflow_sessions_count",
    "agent_runs_count",
    "team_runs_count",
    "workflow_runs_count",
]


def _stored_counts(db: ValkeyDb, days_back: int = 3) -> Dict[Tuple[date, str], Dict[str, int]]:
    """Read back the counts of every day and user from the metrics tables."""
    stored: Dict[Tuple[date, str], Dict[str, int]] = {}
    everyone_rows, _ = db.get_metrics_by_date(_utc_date(days_back), _utc_date(0))
    rows = [{**row, "user_id": "*"} for row in everyone_rows] + db.get_metrics(_utc_date(days_back), _utc_date(0))[0]
    for row in rows:
        counts = {column: row[column] for column in _COUNTS if row[column]}
        counts.update(
            {
                field: row["token_metrics"][field]
                for field in ["input_tokens", "output_tokens", "total_tokens", "cache_read_tokens"]
                if row["token_metrics"][field]
            }
        )
        stored[(row["date"], row["user_id"] or "")] = counts
    for days_ago in range(days_back + 1):
        for user_id in [None, "", "alice", "bob"]:
            totals, _ = db.get_metrics_totals(
                _utc_date(days_ago), _utc_date(days_ago), user_id=user_id, fields=["root_runs_count"]
            )
            if totals["root_runs_count"]:
                stored.setdefault((_utc_date(days_ago), "*" if user_id is None else user_id), {})["root_runs_count"] = (
                    totals["root_runs_count"]
                )
    return {key: counts for key, counts in stored.items() if counts}


def test_calculate_metrics_matches_the_stored_sessions_and_runs(db):
    """Ensure the metrics tables hold, per day, per user and for every user, what a direct count of the sessions and
    runs gives"""
    _seed(db)

    rows = db.calculate_metrics()

    # The day with no session or run has no row
    assert rows is not None and {row["date"] for row in rows} == {_utc_date(day) for day in [3, 2, 0]}
    assert _stored_counts(db) == _ground_truth(db)
    # The member run is counted once, under its own agent, started by the team
    assert db.get_metrics(_utc_date(3), _utc_date(3), user_id="bob")[0][0]["agent_runs_count"] == 1
    totals, _ = db.get_metrics_totals(_utc_date(3), _utc_date(0), fields=["root_runs_count", "cache_read_tokens"])
    assert totals == {"root_runs_count": 7, "cache_read_tokens": 51}


def test_calculate_metrics_rebuilds_a_reopened_day(db):
    """Ensure a paused run resumed after its day closed reopens the day, and the next calculation counts it
    completed"""
    _seed(db)
    _backdate(db)
    db.calculate_metrics()
    versions = _versions(db, _utc_date(3), _utc_date(0))
    day3 = f"daily {_utc_date(3).isoformat()}"

    db.upsert_run(_run("r-paused", int(time.time()), 50, team_id="team-1"), session_id="s-team", user_id="bob")

    assert _versions(db, _utc_date(3), _utc_date(0))[day3] == versions[day3] + 1
    assert [row["date"] for row in db.calculate_metrics()] == [_utc_date(3)] * 3
    assert _stored_counts(db) == _ground_truth(db)
    status, _ = db.get_component_metrics(_utc_date(3), _utc_date(3), fields=["status_metrics"])
    assert status == [{"date": _utc_date(3), "status_metrics": {"COMPLETED": 6}}]


def test_a_session_saved_again_stays_on_the_day_it_was_created(db):
    """Ensure a session saved again with another created_at keeps the stored one, so it is counted on its first
    day"""
    _seed(db)
    db.upsert_session(
        AgentSession(session_id="s-agent", agent_id="agent-1", user_id="alice", created_at=int(time.time()))
    )
    db.upsert_sessions(
        [AgentSession(session_id="s-agent-bob", agent_id="agent-1", user_id="bob", created_at=int(time.time()))]
    )

    db.calculate_metrics()

    assert db.get_metrics(_utc_date(3), _utc_date(3), user_id="alice")[0][0]["agent_sessions_count"] == 1
    assert db.get_metrics(_utc_date(2), _utc_date(2), user_id="bob")[0][0]["agent_sessions_count"] == 1


def _refresh_row(db: ValkeyDb, **values: Any) -> None:
    """Store the row of the metrics refreshes table, as another process would."""
    row = {
        "id": "metrics",
        "locked_by": None,
        "locked_at": None,
        "started_at": int(time.time()),
        "finished_at": None,
        "status": "completed",
        "error": None,
        "fingerprint": None,
        **values,
    }
    db.valkey_client.set(db._metrics_refresh_key(), json.dumps(row))


def test_calculate_metrics_takes_over_a_lock_that_went_stale(db):
    """Ensure a refresh another process holds blocks a calculation, and once its lock went stale it reads failed and
    the next calculation takes it over"""
    _seed(db)
    _refresh_row(db, locked_by="other", locked_at=int(time.time()), status="running")
    assert db.calculate_metrics() is None
    _refresh_row(db, locked_by="other", locked_at=int(time.time()) - METRICS_LOCK_SECONDS, status="running")
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", "The metrics refresh stopped before it finished")

    assert db.calculate_metrics()
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("completed", None)
    assert status["finished_at"] is not None


def test_a_fingerprint_past_14_digits_still_matches(db, monkeypatch):
    """Past ~56k sessions or runs of yesterday and today, the sum of their update times passes 14 digits, so a refresh
    with nothing new still rebuilds nothing."""
    import agno.db.valkey.valkey as valkey_module

    monkeypatch.setattr(
        valkey_module,
        "get_metrics_fingerprint",
        lambda sessions, runs, yesterday: [yesterday.isoformat(), 60000, 107617023359999, 0, 0],
    )
    db.calculate_metrics()

    assert db.calculate_metrics_dates() == []


def test_records_written_before_the_index_are_indexed_by_the_first_calculation(db):
    """Ensure sessions and runs stored without the created_at index, as by an earlier release or the v3 migration,
    are indexed once, so their days are built"""
    _seed(db)
    for table_type in ["sessions", "runs"]:
        db.valkey_client.delete([f"agno:{table_type}:index:created_at"])

    db.calculate_metrics()

    assert _stored_counts(db) == _ground_truth(db)


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column(db):
    """Ensure the runs a 2.x session keeps in its legacy runs field until the v3 migration copies them are counted
    from there, and a run the runs table also holds is counted from the runs table"""
    created_at = _noon_utc(3)
    legacy_runs = [
        {
            **_run("legacy-1", created_at, 100, agent_id="agent-1"),
            "messages": [{"role": "user", "content": "x" * 1000}],
        },
        _run("legacy-2", created_at + 1, 20, agent_id="agent-1"),
    ]
    session = {
        "session_id": "s-legacy",
        "session_type": "agent",
        "agent_id": "agent-1",
        "user_id": "alice",
        "runs": legacy_runs,
        "created_at": created_at,
        "updated_at": created_at + 1,
    }
    db.valkey_client.set(generate_valkey_key("agno", "sessions", "s-legacy"), serialize_data(session))
    # legacy-2 was copied to the runs table, where it has more tokens
    db.upsert_run(_run("legacy-2", created_at + 1, 30, agent_id="agent-1"), session_id="s-legacy", user_id="alice")

    db.calculate_metrics()

    rows, _ = db.get_metrics(_utc_date(3), _utc_date(3), user_id="alice")
    assert (rows[0]["agent_sessions_count"], rows[0]["agent_runs_count"]) == (1, 2)
    assert rows[0]["token_metrics"]["input_tokens"] == 130


def test_calculate_date_metrics_writes_nothing_after_losing_the_lock(db, monkeypatch):
    """Ensure a holder whose lock went stale after its heartbeat, and was taken over, writes nothing: its writes are
    refused in the same script that checks the refresh"""
    _seed(db)
    db.calculate_metrics()
    db.upsert_run(_run("r-paused", int(time.time()), 50, team_id="team-1"), session_id="s-team", user_id="bob")
    versions = _versions(db, _utc_date(3), _utc_date(3))
    heartbeat = db._heartbeat_metrics_refresh

    def taken_over_after_heartbeat(worker_id: str) -> bool:
        held = heartbeat(worker_id)
        refresh_row = json.loads(db.valkey_client.get(db._metrics_refresh_key()))
        db.valkey_client.set(db._metrics_refresh_key(), json.dumps({**refresh_row, "locked_by": "another worker"}))
        return held

    monkeypatch.setattr(db, "_heartbeat_metrics_refresh", taken_over_after_heartbeat)

    assert db.calculate_metrics_dates() is None
    assert _versions(db, _utc_date(3), _utc_date(3)) == versions
    status, _ = db.get_component_metrics(_utc_date(3), _utc_date(3), fields=["status_metrics"])
    assert status == [{"date": _utc_date(3), "status_metrics": {"COMPLETED": 5, "PAUSED": 1}}]


def test_calculate_metrics_counts_tool_calls(db):
    """Ensure each tool call is counted under its tool from the stored run, that a tool call a forked run copied is
    not, and that a totals read adds the tools up"""
    created_at = _noon_utc(2)
    copied_call = {
        "tool_call_id": "copied-call",
        "tool_name": "search",
        "tool_args": {"query": "agno"},
        "result": "x" * 10000,
        "metrics": {"duration": 0.4},
    }
    original = {
        **_run("r-original", created_at, 10, agent_id="agent-1"),
        "messages": [{"role": "tool", "tool_call_id": "copied-call", "content": "agno"}],
        "tools": [copied_call],
    }
    forked = {
        **_run("r-forked", created_at + 1, 10, agent_id="agent-1"),
        "messages": [
            {"role": "tool", "tool_call_id": "copied-call", "content": "agno"},
            {"role": "tool", "tool_call_id": "new-call", "content": "agno"},
        ],
        "tools": [copied_call, {"tool_call_id": "new-call", "tool_name": "search", "metrics": {"duration": 0.1}}],
        "forked_from_message_index": 1,
    }
    _save(
        db,
        AgentSession(session_id="s-fork", agent_id="agent-1", user_id="bob", created_at=created_at),
        [original, forked],
    )

    db.calculate_metrics()

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
    metrics, _ = db.get_component_metrics(_utc_date(2), _utc_date(2), fields=["tool_metrics"])
    assert metrics[0]["tool_metrics"] == expected
    totals, _ = db.get_metrics_totals(_utc_date(2), _utc_date(2), user_id="bob", fields=["tool_metrics"])
    assert totals == {"tool_metrics": expected}


def test_get_metrics_returns_a_day_with_only_a_regenerated_run(db):
    """Ensure a day with only a regenerated run, which has tokens but no count, is returned"""
    _save(
        db,
        AgentSession(session_id="s-dave", agent_id="agent-1", user_id="dave", created_at=_noon_utc(2)),
        [_run("r-dave", _noon_utc(3), 20, agent_id="agent-1", status="REGENERATED")],
    )

    db.calculate_metrics()

    rows, _ = db.get_metrics(_utc_date(3), _utc_date(3), user_id="dave")
    assert [(row["date"], row["token_metrics"]["total_tokens"]) for row in rows] == [(_utc_date(3), 30)]
