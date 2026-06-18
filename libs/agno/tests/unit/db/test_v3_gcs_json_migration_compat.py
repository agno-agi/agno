"""Tests for the v3.0.0 runs-list storage in GcsJsonDb.

Uses a tiny in-memory stub for the GCS client/bucket/blob trio so no real GCS
account is needed.
"""

from __future__ import annotations

import json
import sys
import time
import types
from typing import Any, Dict, List

import pytest

from agno.db.base import SessionType
from agno.models.message import Message
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

    def exists(self) -> bool:
        return self.name in self._bucket._objects

    def download_as_text(self) -> str:
        return self._bucket._objects[self.name]

    def download_as_bytes(self) -> bytes:
        if self.name not in self._bucket._objects:
            raise Exception("404 Not Found")
        return self._bucket._objects[self.name].encode("utf-8")

    def upload_from_string(self, data: str, content_type: str = "application/json") -> None:
        self._bucket._objects[self.name] = data

    def delete(self) -> None:
        self._bucket._objects.pop(self.name, None)


class _FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self._objects: Dict[str, str] = {}

    def blob(self, name: str) -> _FakeBlob:
        return _FakeBlob(self, name)

    def exists(self) -> bool:
        return True

    def list_blobs(self, prefix: str = ""):
        return [_FakeBlob(self, n) for n in list(self._objects.keys()) if n.startswith(prefix)]


class _FakeClient:
    _buckets: Dict[str, _FakeBucket] = {}

    def __init__(self, *args, **kwargs) -> None:
        pass

    def bucket(self, name: str) -> _FakeBucket:
        if name not in _FakeClient._buckets:
            _FakeClient._buckets[name] = _FakeBucket(name)
        return _FakeClient._buckets[name]

    def get_bucket(self, name: str) -> _FakeBucket:
        return self.bucket(name)


@pytest.fixture(autouse=True)
def _patch_gcs(monkeypatch):
    # Make sure agno.db.gcs_json.gcs_json_db.gcs.Client points to the fake.
    from agno.db.gcs_json import gcs_json_db as mod

    fake_gcs = types.SimpleNamespace(Client=_FakeClient)
    monkeypatch.setattr(mod, "gcs", fake_gcs)
    # Reset the buckets between tests so state doesn't leak.
    _FakeClient._buckets = {}
    yield


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


def _new_db():
    from agno.db.gcs_json.gcs_json_db import GcsJsonDb

    return GcsJsonDb(bucket_name="test-bucket", prefix="agno/")


def _insert_legacy_session(db, session_id: str, runs: List[Dict[str, Any]]) -> None:
    existing = db._read_json_file(db.session_table_name, create_table_if_not_found=True) or []
    existing.append(
        {
            "session_id": session_id,
            "session_type": "agent",
            "agent_id": "agent-1",
            "user_id": "u1",
            "runs": runs,
            "session_data": {"session_state": {}},
            "created_at": int(time.time()),
            "updated_at": int(time.time()),
        }
    )
    db._write_json_file(db.session_table_name, existing)


def test_fresh_schema_round_trip():
    db = _new_db()
    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

    sessions = db._read_json_file(db.session_table_name)
    assert len(sessions) == 1 and "runs" not in sessions[0]

    rows = db._read_runs_file()
    assert len(rows) == 2

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]
    assert loaded.runs[0].messages[0].content == "q-one"


def test_legacy_blob_fallback_on_read():
    db = _new_db()
    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s2", runs)

    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


def test_partial_state_merges():
    db = _new_db()
    legacy = [_make_run(f"rl{i}", "s4", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db, "s4", legacy)

    db._write_runs_file(
        [
            {
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
        ]
    )

    loaded = db.get_session("s4", SessionType.AGENT)
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name=db.session_table_name)

    assert len(db._read_runs_file()) == 2

    sessions = db._read_json_file(db.session_table_name)
    assert sessions[0].get("runs") is not None


def test_cleanup_refuses_when_legacy_runs_still_present():
    db = _new_db()
    _insert_legacy_session(db, "s7", [_make_run("r1", "s7", "x").to_dict()])

    with pytest.raises(RuntimeError, match="Refusing to unset"):
        db.cleanup_legacy_runs_field()

    assert db.cleanup_legacy_runs_field(force=True) is True
    sessions = db._read_json_file(db.session_table_name)
    assert "runs" not in sessions[0]


def test_get_run_get_runs_apis():
    db = _new_db()
    session = AgentSession(session_id="sx", agent_id="agent-1", user_id="u1")
    for i in range(3):
        session.upsert_run(_make_run(f"r{i}", "sx", f"c{i}"))
    db.upsert_session(session)

    run = db.get_run("r1")
    assert run is not None and run.content == "c1"

    runs = db.get_runs(session_id="sx")
    assert [r.run_id for r in runs] == ["r0", "r1", "r2"]

    db.delete_session("sx")
    assert len(db._read_runs_file()) == 0
