"""Tests for the v3.0.0 runs-collection migration in FirestoreDb.

Uses ``mock-firestore`` (which exposes the legacy positional ``where(field, op, value)``
API) while the adapter uses the modern ``filter=FieldFilter(...)`` kwarg. We patch
``CollectionReference.where`` and ``Query.where`` to accept either form so the
adapter code can run unchanged.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

mockfirestore = pytest.importorskip("mockfirestore")

from mockfirestore import CollectionReference as _MockCollectionRef  # noqa: E402
from mockfirestore import MockFirestore  # noqa: E402
from mockfirestore import Query as _MockQuery  # noqa: E402


def _make_where_compat(original):
    """Return a where() shim accepting both ``(field, op, value)`` and ``filter=FieldFilter(...)``."""

    def patched_where(self, field=None, op=None, value=None, *, filter=None):  # noqa: A002
        if filter is not None:
            field = getattr(filter, "field_path", None) or getattr(filter, "_field_path", None)
            op = getattr(filter, "op_string", None) or getattr(filter, "_op_string", None)
            value = getattr(filter, "value", None) or getattr(filter, "_value", None)
        return original(self, field, op, value)

    return patched_where


_MockCollectionRef.where = _make_where_compat(_MockCollectionRef.where)
_MockQuery.where = _make_where_compat(_MockQuery.where)


class _MockBatch:
    """A trivial WriteBatch shim that executes operations immediately."""

    def __init__(self):
        self._ops = []

    def set(self, doc_ref, data, merge=False):
        self._ops.append(("set", doc_ref, data, merge))

    def update(self, doc_ref, data):
        self._ops.append(("update", doc_ref, data, False))

    def delete(self, doc_ref):
        self._ops.append(("delete", doc_ref, None, False))

    def commit(self):
        from google.cloud.firestore import DELETE_FIELD

        for kind, doc_ref, data, merge in self._ops:
            if kind == "set":
                doc_ref.set(data, merge=merge) if merge else doc_ref.set(data)
            elif kind == "update":
                # Honor DELETE_FIELD sentinel by stripping the key from the current doc
                snap = doc_ref.get()
                current = snap.to_dict() if snap.exists else {}
                for k, v in data.items():
                    if v is DELETE_FIELD or v == DELETE_FIELD:
                        current.pop(k, None)
                    else:
                        current[k] = v
                doc_ref.set(current)
            elif kind == "delete":
                doc_ref.delete()
        self._ops = []


def _patched_batch(self):
    return _MockBatch()


MockFirestore.batch = _patched_batch  # type: ignore[method-assign]

# The adapter imports `DELETE_FIELD` and `FieldFilter` from google.cloud.firestore.
# Provide a stand-in if google-cloud-firestore isn't installed in the dev env.
try:
    from google.cloud.firestore import DELETE_FIELD, FieldFilter  # type: ignore  # noqa: F401
except ImportError:
    import sys
    import types

    fake = types.ModuleType("google.cloud.firestore")

    class FieldFilter:  # type: ignore[no-redef]
        def __init__(self, field_path: str, op_string: str, value: Any) -> None:
            self.field_path = field_path
            self.op_string = op_string
            self.value = value

    fake.FieldFilter = FieldFilter
    fake.DELETE_FIELD = "__delete_field__"

    class Client:
        pass

    fake.Client = Client
    sys.modules["google.cloud.firestore"] = fake

from agno.db.base import SessionType  # noqa: E402
from agno.db.firestore.firestore import FirestoreDb  # noqa: E402
from agno.models.message import Message  # noqa: E402
from agno.run.agent import RunOutput  # noqa: E402
from agno.run.base import RunStatus  # noqa: E402
from agno.session import AgentSession  # noqa: E402


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


def _new_db() -> FirestoreDb:
    client = MockFirestore()
    return FirestoreDb(db_client=client, session_collection="agno_sessions", runs_collection="agno_runs")


def _insert_legacy_session(db: FirestoreDb, session_id: str, runs: List[Dict[str, Any]]) -> None:
    db.db_client.collection("agno_sessions").add(
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


def test_fresh_schema_round_trip():
    db = _new_db()

    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

    raw_docs = list(db.db_client.collection("agno_sessions").stream())
    assert len(raw_docs) == 1
    raw = raw_docs[0].to_dict()
    assert raw is not None and "runs" not in raw

    run_docs = list(db.db_client.collection("agno_runs").stream())
    assert len(run_docs) == 2

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

    db.db_client.collection("agno_runs").document("rl1").set(
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
    )

    loaded = db.get_session("s4", SessionType.AGENT)
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}


def test_v3_migration_is_non_destructive():
    db = _new_db()
    legacy = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db, "s6", legacy)

    from agno.db.migrations.versions.v3_0_0 import up as v3_up

    v3_up(db, table_type="sessions", table_name="agno_sessions")

    assert len(list(db.db_client.collection("agno_runs").stream())) == 2

    raw_docs = list(db.db_client.collection("agno_sessions").stream())
    raw = raw_docs[0].to_dict()
    assert raw is not None and raw.get("runs") is not None


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
    remaining = list(db.db_client.collection("agno_runs").where("session_id", "==", "sx").stream())
    assert len(remaining) == 0
