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


class _Script:
    def __init__(self, code: str):
        self.code = code


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
        if args[0] == "" and args[1] == "failed" and args[5] == "null":
            if keys[0] in self.strings:
                return 0
            row = {"id": args[7], "locked_by": None, "locked_at": None, "started_at": int(time.time())}
            row.update(finished_at=None, fingerprint=None, status="failed", error=args[3])
            self.strings[keys[0]] = json.dumps(row).encode()
            return 1
        if not self._holds(keys[0], args[0]):
            return 0
        row = {**json.loads(self.strings[keys[0]]), "locked_by": None, "locked_at": None}
        if args[0] == "" and [row["started_at"], row["finished_at"]] != [json.loads(args[5]), json.loads(args[6])]:
            return 0
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

    def _mark_metrics_refresh_rebuild(self, keys, args):
        if keys[0] not in self.strings:
            return 0
        self.strings[keys[0]] = json.dumps(
            {**json.loads(self.strings[keys[0]]), "fingerprint": json.loads(args[0])}
        ).encode()
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

    def _upsert_user_metrics_row(self, keys, args):
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
            valkey_utils.CLAIM_METRICS_REFRESH_LUA: self._claim,
            valkey_utils.HEARTBEAT_METRICS_REFRESH_LUA: self._heartbeat,
            valkey_utils.RELEASE_METRICS_REFRESH_LUA: self._release,
            valkey_utils.MARK_METRICS_REFRESH_REBUILD_LUA: self._mark_metrics_refresh_rebuild,
            valkey_utils.FENCED_METRICS_WRITES_LUA: self._fenced_writes,
            valkey_utils.UPSERT_USER_METRICS_ROW_LUA: self._upsert_user_metrics_row,
        }[script.code]
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
    import agno.db.valkey.utils as valkey_utils
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
    monkeypatch.setattr(valkey_module, "Script", _Script)
    monkeypatch.setattr(valkey_utils, "Script", _Script)
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
        for row in db._get_user_metrics_records(record_ids)
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
    """The metrics tables hold, per day, per user and for every user, what a direct count of the sessions and runs
    gives."""
    _seed(db)

    rows = db.calculate_metrics()

    # The day with no session or run has no row
    assert rows is not None and {row["date"] for row in rows} == {_utc_date(day) for day in [3, 2, 0]}
    assert _stored_counts(db) == _ground_truth(db)
    # The member run is counted once, under its own agent, started by the team
    assert db.get_metrics(_utc_date(3), _utc_date(3), user_id="bob")[0][0]["agent_runs_count"] == 1
    totals, _ = db.get_metrics_totals(_utc_date(3), _utc_date(0), fields=["root_runs_count", "cache_read_tokens"])
    assert totals == {"root_runs_count": 7, "cache_read_tokens": 51}


def test_a_run_save_reopens_its_closed_day(db):
    """A paused run resumed after its day closed reopens the day, and the next calculation counts it completed."""
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


def test_delete_session_keeps_its_closed_day_closed(db):
    """A delete reopens nothing: the deleted usage stays counted until its day is rebuilt."""
    _seed(db)
    _backdate(db)
    db.calculate_metrics()
    versions = _versions(db, _utc_date(3), _utc_date(0))

    db.delete_session("s-agent")

    assert _versions(db, _utc_date(3), _utc_date(0)) == versions
    assert db.calculate_metrics_dates() == []
    assert db.get_metrics(_utc_date(3), _utc_date(3), user_id="alice")[0][0]["agent_sessions_count"] == 1


def test_a_session_saved_again_stays_on_the_day_it_was_created(db):
    """A session saved again with another created_at keeps the stored one, so it is counted on its first day."""
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


def test_calculate_metrics_rebuilds_every_day_from_rebuild_from(db):
    """rebuild_from rebuilds every day with data from the date, completed or not, so a deleted session drops out of
    its day, and a day whose user metrics rows were lost is built again."""
    _seed(db)
    db.calculate_metrics()
    db.delete_session("s-agent")
    for record_id in db._get_metrics_record_ids("user_metrics", "date", [_utc_date(2).isoformat()]):
        db.valkey_client.delete([generate_valkey_key(db._metrics_prefix(), "user_metrics", record_id)])

    rows = db.calculate_metrics(rebuild_from=_utc_date(3))

    assert {row["date"] for row in rows} == {_utc_date(day) for day in [3, 2, 0]}
    assert db.get_metrics(_utc_date(3), _utc_date(3), user_id="alice")[0] == []
    assert _stored_counts(db) == _ground_truth(db)


def test_calculate_metrics_skips_a_refresh_with_nothing_new(db):
    """With no write since the last calculation, the fingerprint of yesterday and today is the same, so nothing is
    rebuilt; a run written today moves only today."""
    _seed(db)
    _backdate(db)
    db.calculate_metrics()
    versions = _versions(db, _utc_date(3), _utc_date(0))

    assert db.calculate_metrics_dates() == []
    # Nothing changed: today's metrics come back
    assert {row["date"] for row in db.calculate_metrics()} == {_utc_date(0)}
    assert _versions(db, _utc_date(3), _utc_date(0)) == versions

    db.upsert_run(_run("r-new", int(time.time()) - 1, 5, team_id="team-1"), session_id="s-team-today", user_id="alice")
    _backdate(db)
    assert {row["date"] for row in db.calculate_metrics()} == {_utc_date(0)}
    new_versions = _versions(db, _utc_date(3), _utc_date(0))
    expected = {f"daily {_utc_date(0).isoformat()}"}
    # The month's row is dated its first day, inside the range only early in the month
    month_key = f"monthly {_utc_date(0).replace(day=1).isoformat()}"
    if month_key in versions:
        expected.add(month_key)
    assert {key for key in versions if new_versions[key] != versions[key]} == expected


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


def test_get_metrics_reads_the_metrics_table_until_the_first_calculation_finished(db):
    """Until a first calculation finished, get_metrics reads agno_metrics and never builds; once it has, a read
    refreshes the new tables at most once a minute, and never on a database AgentOS calculates."""
    _seed(db)
    old_row = {"id": "old", "date": _utc_date(3).isoformat(), "user_id": "carol", "updated_at": 1}
    db.valkey_client.set(generate_valkey_key("agno", "metrics", "old"), serialize_data(old_row))

    assert [row["id"] for row in db.get_metrics()[0]] == ["old"]
    assert db.get_metrics_refresh_status() is None

    db.calculate_metrics()
    db.upsert_run(_run("r-new", int(time.time()) - 1, 5, team_id="team-1"), session_id="s-team-today", user_id="alice")
    db._metrics_refreshed_at = 0.0
    rows, _ = db.get_metrics(_utc_date(0), _utc_date(0), user_id="alice")
    assert rows[0]["team_runs_count"] == 2
    refreshed_at = db._metrics_refreshed_at
    db.get_metrics(_utc_date(3), _utc_date(0))
    assert db._metrics_refreshed_at == refreshed_at

    db.stop_metrics_refresh_on_read()
    db.upsert_run(
        _run("r-new-2", int(time.time()) - 1, 5, team_id="team-1"), session_id="s-team-today", user_id="alice"
    )
    assert db.get_metrics(_utc_date(0), _utc_date(0), user_id="alice")[0][0]["team_runs_count"] == 2


def test_metrics_calculation_turned_off_stops_the_refresh_on_read(db, monkeypatch):
    """METRICS_CALCULATION_ENABLED=false stops the refresh on read, as it stops AgentOS calculating."""
    _seed(db)
    monkeypatch.setenv("METRICS_CALCULATION_ENABLED", "false")

    db.calculate_metrics()
    db.upsert_run(_run("r-new", int(time.time()) - 1, 5, team_id="team-1"), session_id="s-team-today", user_id="alice")
    db._metrics_refreshed_at = 0.0

    assert db.get_metrics(_utc_date(0), _utc_date(0), user_id="alice")[0][0]["team_runs_count"] == 1


def test_get_metrics_omits_days_without_sessions_or_runs(db):
    """A day without sessions or runs keeps an everyone row of zeros, which a read never returns."""
    _seed(db)
    db.calculate_metrics()

    # The day's everyone row is stored; on the first day of a month, the month's row is dated that day too
    assert _versions(db, _utc_date(1), _utc_date(1))[f"daily {_utc_date(1).isoformat()}"] == 1
    assert db.get_metrics_by_date(_utc_date(1), _utc_date(1))[0] == []
    assert db.get_metrics(_utc_date(1), _utc_date(1))[0] == []


def test_records_written_before_the_index_are_indexed_by_the_first_calculation(db):
    """Sessions and runs stored without the created_at index, as by an earlier release or the v3 migration, are
    indexed once, so their days are built."""
    _seed(db)
    for table_type in ["sessions", "runs"]:
        db.valkey_client.delete([f"agno:{table_type}:index:created_at"])

    db.calculate_metrics()

    assert _stored_counts(db) == _ground_truth(db)


def test_a_rebuild_indexes_records_saved_without_the_index_since(db):
    """Sessions and runs an earlier release saves after the first calculation, as during a rolling deploy, are in no
    sorted set; a rebuild indexes them, so their days are built."""
    _seed(db)
    db.calculate_metrics()
    day1 = _noon_utc(1)
    _save(
        db,
        AgentSession(session_id="s-earlier", agent_id="agent-1", user_id="bob", created_at=day1),
        [_run("r-earlier", day1, 20, agent_id="agent-1")],
    )
    for table_type, record_id in [("sessions", "s-earlier"), ("runs", "r-earlier")]:
        db.valkey_client.zrem(f"agno:{table_type}:index:created_at", [record_id])

    db.calculate_metrics(rebuild_from=_utc_date(3))

    assert _stored_counts(db) == _ground_truth(db)


def test_calculate_metrics_counts_runs_kept_in_the_legacy_runs_column(db):
    """A 2.x session keeps its runs in its legacy runs field until the v3 migration copies them; they are counted
    from there, and a run the runs table also holds is counted from the runs table."""
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


def test_a_legacy_run_is_counted_on_its_own_day(db):
    """A legacy run created on a day after its session's is counted on that day, which holds no session or run of the
    tables."""
    created_at = _noon_utc(5)
    session = {
        "session_id": "s-legacy",
        "session_type": "agent",
        "agent_id": "agent-1",
        "user_id": "alice",
        "runs": [
            _run("legacy-1", created_at, 100, agent_id="agent-1"),
            _run("legacy-2", _noon_utc(3), 20, agent_id="agent-1"),
        ],
        "created_at": created_at,
        "updated_at": _noon_utc(3),
    }
    db.valkey_client.set(generate_valkey_key("agno", "sessions", "s-legacy"), serialize_data(session))

    db.calculate_metrics()

    rows, _ = db.get_metrics(_utc_date(5), _utc_date(3), user_id="alice")
    assert [(row["date"], row["agent_runs_count"]) for row in rows] == [(_utc_date(5), 1), (_utc_date(3), 1)]


def test_upsert_run_reopens_a_day_a_write_could_not_reopen(db, monkeypatch):
    """A failed reopen never fails the save, and the next write reopens the day."""
    _seed(db)
    db.calculate_metrics()
    versions = _versions(db, _utc_date(3), _utc_date(0))
    day3 = f"daily {_utc_date(3).isoformat()}"

    original_exists = db.valkey_client.exists
    monkeypatch.setattr(db.valkey_client, "exists", lambda *keys: (_ for _ in ()).throw(ConnectionError("down")))
    db.upsert_run(_run("r-paused", int(time.time()), 50, team_id="team-1"), session_id="s-team", user_id="bob")
    assert db._metrics_days_not_reopened == {_utc_date(3)}
    assert _versions(db, _utc_date(3), _utc_date(0))[day3] == versions[day3]

    monkeypatch.setattr(db.valkey_client, "exists", original_exists)
    db.upsert_run(_run("r-new", int(time.time()) - 1, 5, team_id="team-1"), session_id="s-team-today", user_id="alice")
    assert db._metrics_days_not_reopened == set()
    assert _versions(db, _utc_date(3), _utc_date(0))[day3] == versions[day3] + 1


def test_calculate_metrics_dates_releases_the_lock_when_stopped(db):
    """A first calculation stopped between days releases the refresh as failed; a later one stopped leaves it as the
    last completed one left it, and the days it did not reach to the next."""
    _seed(db)

    assert db.calculate_metrics_dates(should_stop=lambda: True) is None
    status = db.get_metrics_refresh_status()
    assert (status["status"], status["error"]) == ("failed", "The metrics refresh stopped before it finished")
    assert db.calculate_metrics()

    db.upsert_run(_run("r-new", int(time.time()) - 1, 5, team_id="team-1"), session_id="s-team-today", user_id="alice")
    assert db.calculate_metrics_dates(should_stop=lambda: True) is None
    assert db.get_metrics_refresh_status()["status"] == "completed"
    assert db.calculate_metrics_dates() == [_utc_date(1), _utc_date(0)]


def test_calculate_metrics_rebuilds_a_month_a_stopped_calculation_left(db):
    """A day rebuilt by a calculation that stops before its months reopens its month, so the next calculation
    rebuilds the month and a read of the whole month never takes the stale month row."""
    month_start = (_utc_date(0).replace(day=1) - timedelta(days=1)).replace(day=1)
    if (_utc_date(0) - month_start).days < 40:
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    day = month_start + timedelta(days=4)
    created_at = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
    _save(
        db,
        AgentSession(session_id="s-month", agent_id="agent-1", user_id="alice", created_at=created_at),
        [_run("r-month", created_at, 100, agent_id="agent-1")],
    )
    db.calculate_metrics()
    db.upsert_run(_run("r-month", created_at, 1000, agent_id="agent-1"), session_id="s-month", user_id="alice")

    # Checked before the day, between the day's two reads and before its month: stopped at the month
    checks = iter([False, False, False, True])
    assert db.calculate_metrics_dates(should_stop=lambda: next(checks)) is None

    totals, _ = db.get_metrics_totals(month_start, month_end, fields=["input_tokens"])
    assert totals == {"input_tokens": 1000}
    db.calculate_metrics()
    month_rows = db._get_user_metrics_records(
        [record_id for record_id in db._get_metrics_everyone_record_ids() if record_id.endswith("_monthly")]
    )
    assert [(row["input_tokens"], row["completed"]) for row in month_rows if row["date"] == month_start] == [
        (1000, True)
    ]


def test_get_metrics_totals_reads_a_whole_month_from_its_month_rows(db):
    """A completed month gets month rows, counted over the month, and a range holding the whole month reads them."""
    month_start = (_utc_date(0).replace(day=1) - timedelta(days=1)).replace(day=1)
    if (_utc_date(0) - month_start).days < 40:
        month_start = (month_start - timedelta(days=1)).replace(day=1)
    for offset, user_id in [(0, "alice"), (9, "alice"), (3, "bob")]:
        day = month_start + timedelta(days=offset)
        created_at = int(datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp())
        _save(
            db,
            AgentSession(session_id=f"s-{offset}", agent_id="agent-1", user_id=user_id, created_at=created_at),
            [_run(f"r-{offset}", created_at, 100 + offset, agent_id="agent-1")],
        )

    db.calculate_metrics()

    month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    assert f"monthly {month_start.isoformat()}" in _versions(db, month_start, month_end)
    month_row = db._get_user_metrics_records(
        [
            record_id
            for record_id in db._get_metrics_everyone_record_ids()
            if metrics_record_key(record_id)[1] == "monthly"
        ]
    )
    assert [(row["users_count"], row["completed"]) for row in month_row if row["date"] == month_start] == [(2, True)]
    totals, _ = db.get_metrics_totals(month_start, _utc_date(0), fields=["root_runs_count", "input_tokens"])
    assert totals == {"root_runs_count": 3, "input_tokens": 312}
    totals, _ = db.get_metrics_totals(month_start, month_end, user_id="alice", fields=["input_tokens"])
    assert totals == {"input_tokens": 209}
    days, _ = db.get_component_metrics(month_start, month_end, user_id="bob", fields=["input_tokens"])
    assert days == [{"date": month_start + timedelta(days=3), "input_tokens": 103}]


def test_get_metrics_versions(db):
    """None until a first calculation finished; then the version of every everyone row of the range, which moves when
    a reopened day is rebuilt."""
    _seed(db)
    assert db.get_metrics_versions(_utc_date(3), _utc_date(0)) is None

    db.calculate_metrics()
    versions = db.get_metrics_versions(_utc_date(3), _utc_date(0))
    assert {key for key in versions if key.startswith("daily")} == {
        f"daily {_utc_date(day).isoformat()}" for day in [3, 2, 1, 0]
    }
    assert versions == _versions(db, _utc_date(3), _utc_date(0))

    db.upsert_run(_run("r-paused", int(time.time()), 50, team_id="team-1"), session_id="s-team", user_id="bob")
    db._metrics_refreshed_at = 0.0
    new_versions = db.get_metrics_versions(_utc_date(3), _utc_date(3))
    # Reopened, then rebuilt by the refresh before the read
    assert new_versions[f"daily {_utc_date(3).isoformat()}"] == versions[f"daily {_utc_date(3).isoformat()}"] + 2
    assert db.get_metrics_versions(_utc_date(3), _utc_date(3)) == new_versions


def test_calculate_metrics_counts_a_remote_member_run_once(db):
    """A remote member's run kept inside its team run and stored as a run of its own by the AgentOS that ran it, in the
    same database, is counted once, from its own row, and its session is not counted."""
    day2 = _noon_utc(2)
    member_run = {
        **_run("r-remote", day2, 10, agent_id="remote-agent", parent_run_id="r-team"),
        "session_id": "s-team:remote-agent",
    }
    _save(
        db,
        TeamSession(session_id="s-team", team_id="team-1", user_id="bob", created_at=day2),
        [_run("r-team", day2, 0, team_id="team-1", member_responses=[member_run])],
    )
    # The remote AgentOS stores its run, with no parent, in a session of its own
    _save(
        db,
        AgentSession(session_id="s-team:remote-agent", agent_id="remote-agent", user_id="bob", created_at=day2),
        [{**member_run, "parent_run_id": None}],
    )

    db.calculate_metrics()

    totals, _ = db.get_metrics_totals(_utc_date(2), _utc_date(2), fields=["root_runs_count", "input_tokens"])
    assert totals == {"root_runs_count": 1, "input_tokens": 10}
    assert db.get_metrics(_utc_date(2), _utc_date(2), user_id="bob")[0][0]["agent_sessions_count"] == 0


def test_calculate_metrics_builds_no_month_before_its_last_day_can_be_completed(db):
    """The current month is only reopened by its days, never built, until its last day can be completed."""
    _seed(db)

    db.calculate_metrics()

    month_key = f"monthly {_utc_date(0).replace(day=1).isoformat()}"
    assert _versions(db, _utc_date(0).replace(day=1), _utc_date(0)).get(month_key, 1) == 1


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_completes(db):
    """rebuild_from leaves yesterday and today to the next calculation when another process holds the metrics refresh
    and completes it with the fingerprint it read before the rebuild."""
    _seed(db)
    _backdate(db)
    db.calculate_metrics()
    refresh_row = db._claim_metrics_refresh("other")
    assert refresh_row is not None and refresh_row["fingerprint"] is not None

    assert db.calculate_metrics(rebuild_from=_utc_date(3)) is None

    db._release_metrics_refresh(
        "other", fingerprint=refresh_row["fingerprint"], claimed_fingerprint=refresh_row["fingerprint"]
    )
    assert db.calculate_metrics_dates() == [_utc_date(day) for day in [3, 2, 1, 0]]
    assert db.calculate_metrics_dates() == []


def test_calculate_metrics_rebuild_from_rebuilds_yesterday_and_today_after_another_process_claimed_no_fingerprint(db):
    """rebuild_from leaves yesterday and today to the next calculation when another process holds a metrics refresh it
    claimed with no fingerprint stored, and completes it with a fingerprint."""
    _seed(db)
    _backdate(db)
    db.calculate_metrics()
    fingerprint = db._claim_metrics_refresh("other")["fingerprint"]
    db._release_metrics_refresh("other", fingerprint=None, claimed_fingerprint=fingerprint)
    refresh_row = db._claim_metrics_refresh("other")
    assert refresh_row is not None and refresh_row["fingerprint"] is None

    assert db.calculate_metrics(rebuild_from=_utc_date(0)) is None

    db._release_metrics_refresh("other", fingerprint=fingerprint, claimed_fingerprint=None)
    assert db.calculate_metrics_dates() == [_utc_date(1), _utc_date(0)]
    assert db.calculate_metrics_dates() == []


def test_calculate_metrics_rebuild_from_records_a_failed_reopen(db, monkeypatch):
    """A rebuild whose reopen fails shows the error in the refresh status."""
    _seed(db)
    db.calculate_metrics()

    def fail_reopen() -> List[str]:
        raise ConnectionError("reopen failed")

    monkeypatch.setattr(db, "_get_metrics_everyone_record_ids", fail_reopen)
    with pytest.raises(ConnectionError):
        db.calculate_metrics(rebuild_from=_utc_date(3))

    refresh_row = json.loads(db.valkey_client.get(db._metrics_refresh_key()))
    assert (refresh_row["status"], refresh_row["error"], refresh_row["locked_by"]) == ("failed", "reopen failed", None)


def test_calculate_metrics_counts_a_remote_member_run_two_days_after_its_team_run_as_a_root_run(db):
    """A remote member's run two days after its team run names itself as its root, as only the day before is read for
    its team's run."""
    member_run = {
        **_run("r-remote", _noon_utc(1), 10, agent_id="remote-agent", parent_run_id="r-team"),
        "session_id": "s-team:remote-agent",
    }
    _save(
        db,
        TeamSession(session_id="s-team", team_id="team-1", user_id="bob", created_at=_noon_utc(3)),
        [_run("r-team", _noon_utc(3), 0, team_id="team-1", member_responses=[member_run])],
    )
    _save(
        db,
        AgentSession(session_id="s-team:remote-agent", agent_id="remote-agent", user_id="bob", created_at=_noon_utc(1)),
        [{**member_run, "parent_run_id": None}],
    )

    db.calculate_metrics()

    rows = db._get_component_metrics_records(
        db._get_metrics_record_ids("component_metrics", "date", [_utc_date(1).isoformat()])
    )
    assert [(row["component_id"], row["root_component_id"]) for row in rows] == [("remote-agent", "remote-agent")]
