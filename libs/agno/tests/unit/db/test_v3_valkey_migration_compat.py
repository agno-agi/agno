"""Tests for the v3.0.0 per-run-key storage in ValkeyDb.

Uses a tiny in-memory stub for the GLIDE client so no real Valkey instance is
needed. GLIDE has no published fake, so the stub lives here.
"""

from __future__ import annotations

import fnmatch
import time
from typing import Any, Dict, List, Optional

import pytest

from agno.db.base import SessionType
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession

# ---------------------------------------------------------------------------
# In-memory GLIDE client stub
#
# Backed by one dict per Valkey type, so a key created as a set or sorted set
# raises WRONGTYPE on GET exactly as a real server does — that failure is what
# the runs helper-key filters exist to avoid.
# ---------------------------------------------------------------------------


class _RequestError(Exception):
    pass


class _RangeByIndex:
    def __init__(self, start: int, end: int):
        self.start = start
        self.end = end


class _ExpirySet:
    def __init__(self, expiry_type: Any = None, value: Any = None):
        self.value = value


class _ExpiryType:
    SEC = "SEC"


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

    def zadd(self, key, members_scores):
        self.commands.append(("zadd", key, members_scores))

    def expire(self, key, seconds):
        self.commands.append(("expire", key, seconds))


class _FakeGlideClient:
    def __init__(self):
        self.strings: Dict[str, bytes] = {}
        self.sets: Dict[str, set] = {}
        self.zsets: Dict[str, Dict[str, float]] = {}

    @classmethod
    def create(cls, config: Any = None):
        return cls()

    def _kind(self, key: str) -> Optional[str]:
        if key in self.strings:
            return "string"
        if key in self.sets:
            return "set"
        if key in self.zsets:
            return "zset"
        return None

    # -- strings --

    def get(self, key, buffer=None):
        if self._kind(key) in ("set", "zset"):
            raise _RequestError("WRONGTYPE Operation against a key holding the wrong kind of value")
        return self.strings.get(key)

    def set(self, key, value, expiry=None, **kwargs):
        self.strings[key] = value.encode() if isinstance(value, str) else value
        return "OK"

    def delete(self, keys):
        deleted = 0
        for key in keys:
            for store in (self.strings, self.sets, self.zsets):
                if key in store:
                    del store[key]
                    deleted += 1
        return deleted

    def scan(self, cursor="0", match=None, count=None):
        keys = list(self.strings) + list(self.sets) + list(self.zsets)
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
        members = [m.encode() for m, _ in ordered]
        end = len(members) if range_query.end == -1 else range_query.end + 1
        return members[range_query.start : end]

    def zrem(self, key, members):
        entries = self.zsets.get(key, {})
        for member in members:
            entries.pop(member, None)
        return len(members)

    def expire(self, key, seconds, option=None):
        return True

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
                elif op == "zadd":
                    results.append(self.zadd(command[1], command[2]))
                else:
                    results.append(True)
            except _RequestError as exc:
                # GLIDE surfaces per-command failures as values, not raises
                results.append(exc)
        return results


def _new_db():
    """Build a ValkeyDb on the stub, with the GLIDE types patched to match."""
    import agno.db.valkey.valkey as valkey_module
    from agno.db.valkey.valkey import ValkeyDb

    client = _FakeGlideClient()
    db = ValkeyDb(valkey_client=client, db_prefix="agno")
    valkey_module.RangeByIndex = _RangeByIndex  # type: ignore[assignment]
    valkey_module.RequestError = _RequestError  # type: ignore[assignment]
    valkey_module.ExpirySet = _ExpirySet  # type: ignore[assignment]
    valkey_module.ExpiryType = _ExpiryType  # type: ignore[assignment]
    db._create_pipeline = lambda: _Batch()  # type: ignore[method-assign]
    db._exec_pipeline = lambda pipeline: client.exec(pipeline)  # type: ignore[method-assign]
    return db


def _make_run(run_id: str, session_id: str, content: str) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="agent-1",
        session_id=session_id,
        content=content,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content=f"q-{content}"),
            Message(role="assistant", content=f"a-{content}"),
        ],
    )


def _new_session(session_id: str) -> AgentSession:
    now = int(time.time())
    return AgentSession(session_id=session_id, agent_id="agent-1", user_id="u1", created_at=now, updated_at=now)


def _insert_legacy_session(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    """Write a v2.x-shaped session record directly (with inline `runs` field)."""
    from agno.db.valkey.utils import generate_valkey_key, serialize_data

    data = {
        "session_id": session_id,
        "session_type": "agent",
        "agent_id": "agent-1",
        "user_id": "u1",
        "runs": runs,
        "session_data": {"session_state": {}},
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    key = generate_valkey_key(prefix=db.db_prefix, table_type="sessions", key_id=session_id)
    db.valkey_client.set(key, serialize_data(data))


def test_fresh_schema_round_trip():
    db = _new_db()

    session = _new_session("s1")
    r1 = _make_run("r1", "s1", "one")
    r2 = _make_run("r2", "s1", "two")
    session.upsert_run(r1)
    session.upsert_run(r2)
    db.upsert_session(session)
    db.upsert_run(run=r1, session_id="s1", user_id="u1", run_index=0)
    db.upsert_run(run=r2, session_id="s1", user_id="u1", run_index=1)

    # Session record has no `runs` field
    raw = db._get_record("sessions", "s1")
    assert raw is not None and "runs" not in raw

    # Runs collection has both
    rows, total = db.get_runs(session_id="s1", deserialize=False)
    assert total == 2

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]
    assert loaded.runs[0].messages[0].content == "q-one"


def test_legacy_blob_fallback_on_read():
    db = _new_db()
    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s2", runs)

    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


def test_partial_state_merges_collection_and_blob():
    db = _new_db()
    legacy = [_make_run(f"rl{i}", "s4", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s4", legacy)

    # Migrate just one of the legacy runs into the runs keys via the helper directly
    middle = {
        "run_id": "rl1",
        "session_id": "s4",
        "run_type": "agent",
        "agent_id": "agent-1",
        "user_id": "u1",
        "status": "COMPLETED",
        "run_index": 1,
        "run_data": legacy[1],
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    db._store_record("runs", "rl1", middle, index_fields=["session_id"])
    db.valkey_client.zadd(db._runs_by_session_index_key("s4"), {"rl1": 1.0})

    loaded = db.get_session("s4", SessionType.AGENT)
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name="agno_sessions")

    # Runs are in the runs keys
    rows, total = db.get_runs(session_id="s6", deserialize=False)
    assert total == 2

    # Legacy field is preserved on the session record
    raw = db._get_record("sessions", "s6")
    assert raw is not None and raw.get("runs") is not None


def test_cleanup_refuses_when_legacy_runs_still_present():
    db = _new_db()
    _insert_legacy_session(db, "s7", [_make_run("r1", "s7", "x").to_dict()])

    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    assert db.cleanup_legacy_runs_field(force=True) is True
    raw = db._get_record("sessions", "s7")
    assert raw is not None and "runs" not in raw


def test_get_run_get_runs_apis():
    db = _new_db()
    session = _new_session("sx")
    runs = [_make_run(f"r{i}", "sx", f"c{i}") for i in range(3)]
    for r in runs:
        session.upsert_run(r)
    db.upsert_session(session)
    for idx, r in enumerate(runs):
        db.upsert_run(run=r, session_id="sx", user_id="u1", run_index=idx)

    run = db.get_run("r1")
    assert run is not None and run.content == "c1"

    loaded_runs = db.get_runs(session_id="sx")
    assert [r.run_id for r in loaded_runs] == ["r0", "r1", "r2"]

    db.delete_session("sx")
    # All run keys + the sorted-set index should be gone
    rows, total = db.get_runs(session_id="sx", deserialize=False)
    assert total == 0


def test_delete_run_scrubs_legacy_blob():
    """Deleting a run must not leave it resurrectable from the legacy blob."""
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s11", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s11", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name="agno_sessions")

    assert db.delete_run("r0") is True

    loaded = db.get_session("s11", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1"]


def test_delete_sessions_cascades_runs():
    db = _new_db()
    session = _new_session("s13")
    run = _make_run("r0", "s13", "c0")
    session.upsert_run(run)
    db.upsert_session(session)
    db.upsert_run(run=run, session_id="s13", user_id="u1", run_index=0)

    db.delete_sessions(["s13"])

    assert db.get_run("r0") is None
    rows, total = db.get_runs(session_id="s13", deserialize=False)
    assert total == 0


def test_ids_containing_the_index_marker_stay_visible():
    """The helper-key filters are namespace-anchored, not substring matches.

    A caller-supplied id may legitimately contain `:by_session:` or `:index:`. Those
    records are real keys, and filtering them by substring hides them from every
    list API while direct-by-id reads keep working.
    """
    db = _new_db()
    ids = ["plain", "tenant:by_session:42", "tenant:index:42"]
    for sid in ids:
        db.upsert_session(_new_session(sid))

    rows, total = db.get_sessions(deserialize=False)
    assert total == len(ids)
    assert {r["session_id"] for r in rows} == set(ids)
    for sid in ids:
        assert db.get_session(sid, SessionType.AGENT) is not None


def test_session_and_get_runs_agree_when_run_index_ties():
    """Concurrent runs on one session all resolve to the same `run_index`
    (`resolve_run_index` reads the in-memory session), and ZRANGE then breaks the tie
    lexicographically by run_id. The session read must apply the same
    (run_index, created_at) ordering `get_runs` does."""
    db = _new_db()
    db.upsert_session(_new_session("tie"))

    first = _make_run("zzz-first", "tie", "first")
    first.created_at = 1000
    second = _make_run("aaa-second", "tie", "second")
    second.created_at = 2000
    db.upsert_run(run=first, session_id="tie", user_id="u1", run_index=0)
    db.upsert_run(run=second, session_id="tie", user_id="u1", run_index=0)

    via_session = [r.run_id for r in db.get_session("tie", SessionType.AGENT).runs]
    via_get_runs = [r.run_id for r in db.get_runs(session_id="tie")]

    assert via_session == ["zzz-first", "aaa-second"]
    assert via_session == via_get_runs


def test_runs_index_key_is_not_read_as_a_run_record():
    """`<prefix>:runs:by_session:<id>` matches the `runs` scan pattern; it is a
    sorted set, not a run record, so the scan must skip it."""
    db = _new_db()
    session = _new_session("s14")
    run = _make_run("r0", "s14", "c0")
    session.upsert_run(run)
    db.upsert_session(session)
    db.upsert_run(run=run, session_id="s14", user_id="u1", run_index=0)

    records = db._get_all_records("runs")
    assert [r["run_id"] for r in records] == ["r0"]


def test_upgrade_without_migration_preserves_runs_on_write():
    """Regression: upgrading to v3 and continuing a pre-v3 session before running
    the migration must not silently drop the legacy runs blob.

    Bug shape: session.to_dict(include_runs=False) omits `runs`; the Valkey
    _store_record does a full SET (whole-record replace), so a bare write
    would erase anything the legacy blob was holding. Read then merges an
    empty legacy blob with an empty runs store -> history gone. Only
    cleanup_legacy_runs_field() should drop it, explicitly.
    """
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s_upgrade", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s_upgrade", legacy)

    # Sanity: pre-v3 read sees the runs via the merge helper.
    before = db.get_session(session_id="s_upgrade", session_type=SessionType.AGENT)
    assert before is not None
    assert [r.run_id for r in (before.runs or [])] == ["r0", "r1", "r2"]

    # Simulate a v3 code path continuing this session: reload + save the
    # session row (as _cleanup_and_store would). Under v3, save_session does
    # not write runs -- new runs go to the runs store via save_run.
    reloaded = db.get_session(session_id="s_upgrade", session_type=SessionType.AGENT)
    assert reloaded is not None
    reloaded.metadata = {"touched_by_v3": True}
    db.upsert_session(reloaded)

    # After the v3 write, the legacy blob must still be intact -- the read
    # returns the same three pre-v3 runs.
    after = db.get_session(session_id="s_upgrade", session_type=SessionType.AGENT)
    assert after is not None
    assert [r.run_id for r in (after.runs or [])] == ["r0", "r1", "r2"], (
        "legacy runs blob was wiped by upsert_session -- pre-v3 history lost"
    )
    # And the metadata write actually landed.
    assert after.metadata == {"touched_by_v3": True}


def test_cleanup_after_migration_requires_force():
    """Preserve-blob-on-write means the legacy field stays as a frozen backup
    even after a v3 write. Non-force cleanup refuses; force=True reclaims it."""
    db = _new_db()
    legacy = [_make_run("r1", "s_cleanup", "x").to_dict()]
    _insert_legacy_session(db, "s_cleanup", legacy)

    # A v3 write must not unset the legacy field.
    session = db.get_session("s_cleanup", SessionType.AGENT)
    db.upsert_session(session)

    raw = db._get_record("sessions", "s_cleanup")
    assert raw is not None and raw.get("runs") is not None

    # Non-force cleanup refuses while a legacy blob is still present.
    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    # force=True reclaims it.
    assert db.cleanup_legacy_runs_field(force=True) is True
    raw = db._get_record("sessions", "s_cleanup")
    assert raw is not None and "runs" not in raw
