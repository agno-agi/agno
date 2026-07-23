"""Regression tests for reviewer comment #7 on PR #8350.

During partial-migration state (v3 in progress, ``cleanup_legacy_runs_field``
not yet run), each session document still carries the pre-migration ``runs``
blob as a backup. If ``delete_run(rid)`` only removes the run from the runs
table and doesn't scrub the legacy blob, the read path's
``merge_runs_table_with_legacy_blob`` resurrects the deleted run — a
data-integrity bug.

These tests reproduce the ghost-run scenario end-to-end against JsonDb (the
adapter the reviewer explicitly asked about, and the one we can exercise
without spinning up a native driver) and cover the parallel scrub path added
to every doc adapter.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from agno.db.in_memory.in_memory_db import InMemoryDb
from agno.db.json.json_db import JsonDb
from agno.db.migrations.versions.v3_0_0 import _migrate_jsondb


@pytest.fixture
def json_db_partially_migrated():
    """A JsonDb in partial-migration state: v3 migration copied runs into
    ``agno_runs.json`` but the legacy ``runs`` field on each session doc is
    still present (as the migration guide advertises for rollback safety)."""
    tmp = tempfile.mkdtemp()
    db = JsonDb(db_path=tmp)
    session_row = {
        "session_id": "s1",
        "session_type": "agent",
        "agent_id": "a1",
        "user_id": "u1",
        "runs": [
            {"run_id": "r0", "agent_id": "a1", "status": "COMPLETED", "created_at": 1},
            {"run_id": "r1", "agent_id": "a1", "status": "COMPLETED", "created_at": 2},
            {"run_id": "r2", "agent_id": "a1", "status": "COMPLETED", "created_at": 3},
        ],
        "created_at": 1,
        "updated_at": 1,
    }
    sessions_file = os.path.join(tmp, "agno_sessions.json")
    with open(sessions_file, "w") as f:
        json.dump([session_row], f)
    _migrate_jsondb(db, "agno_sessions")
    return db, tmp, sessions_file


def _read_legacy_blob(sessions_file: str) -> list[str]:
    with open(sessions_file) as f:
        s = json.load(f)
    return [r["run_id"] for r in s[0].get("runs") or []]


class TestJsonDbDeleteRunScrubsLegacyBlob:
    """Reviewer comment #7 — delete_run must also remove the run from the
    legacy blob, otherwise the merge helper resurrects it on read."""

    def test_delete_run_removes_from_both_surfaces(self, json_db_partially_migrated):
        db, _, sessions_file = json_db_partially_migrated

        # Pre-check: both surfaces have all 3 runs
        rows, _total = db.get_runs(deserialize=False)
        assert set(r["run_id"] for r in rows) == {"r0", "r1", "r2"}
        assert _read_legacy_blob(sessions_file) == ["r0", "r1", "r2"]

        db.delete_run("r0")

        # Runs table cleaned
        rows_after, _ = db.get_runs(deserialize=False)
        assert set(r["run_id"] for r in rows_after) == {"r1", "r2"}

        # Legacy blob ALSO cleaned — this is the fix
        assert _read_legacy_blob(sessions_file) == ["r1", "r2"], (
            "delete_run must scrub the legacy blob too; otherwise "
            "merge_runs_table_with_legacy_blob resurrects the deleted run."
        )

    def test_get_session_does_not_resurrect_deleted_run(self, json_db_partially_migrated):
        """The observable-through-the-API check: after deletion, get_session
        must not return the deleted run in its merged list."""
        db, _, _ = json_db_partially_migrated

        db.delete_run("r1")

        sess = db.get_session(session_id="s1", deserialize=False)
        run_ids = [r["run_id"] for r in sess.get("runs") or []]
        assert "r1" not in run_ids, (
            f"deleted r1 resurrected via legacy blob on read: got {run_ids}"
        )
        assert run_ids == ["r0", "r2"]

    def test_delete_runs_bulk_removes_from_both_surfaces(self, json_db_partially_migrated):
        db, _, sessions_file = json_db_partially_migrated

        db.delete_runs(["r0", "r2"])

        rows_after, _ = db.get_runs(deserialize=False)
        assert [r["run_id"] for r in rows_after] == ["r1"]
        assert _read_legacy_blob(sessions_file) == ["r1"]

        # And observable via get_session
        sess = db.get_session(session_id="s1", deserialize=False)
        assert [r["run_id"] for r in sess.get("runs") or []] == ["r1"]

    def test_delete_run_not_in_legacy_blob_is_still_ok(self, json_db_partially_migrated):
        """Runs added *after* migration (in the runs table only) can be
        deleted without incident — the scrub finds no matching legacy entry
        and is a no-op there."""
        db, _, sessions_file = json_db_partially_migrated

        # A post-migration write lives only in the runs table
        db.upsert_run(
            run={"run_id": "r3", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED"},
            session_id="s1",
            user_id="u1",
            run_index=3,
        )

        assert _read_legacy_blob(sessions_file) == ["r0", "r1", "r2"]  # unchanged

        db.delete_run("r3")

        # r3 gone from runs; blob still intact.
        rows_after, _ = db.get_runs(deserialize=False)
        assert "r3" not in {r["run_id"] for r in rows_after}
        assert _read_legacy_blob(sessions_file) == ["r0", "r1", "r2"]

    def test_delete_unknown_run_id_is_a_noop(self, json_db_partially_migrated):
        db, _, sessions_file = json_db_partially_migrated

        result = db.delete_run("does-not-exist")
        assert result is False

        # Nothing else changed
        rows, _ = db.get_runs(deserialize=False)
        assert set(r["run_id"] for r in rows) == {"r0", "r1", "r2"}
        assert _read_legacy_blob(sessions_file) == ["r0", "r1", "r2"]

    def test_delete_run_empty_legacy_blob_is_a_noop(self):
        """Fresh v3 DB (no partial-migration state) — delete_run works and the
        scrub finds nothing to clean."""
        tmp = tempfile.mkdtemp()
        db = JsonDb(db_path=tmp)

        # No sessions_file at all → scrub silently no-ops
        db.upsert_run(
            run={"run_id": "r0", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED"},
            session_id="s1",
            user_id="u1",
            run_index=0,
        )
        assert db.delete_run("r0") is True


class TestInMemoryDbDeleteRunDoesNotResurrect:
    """Sanity: InMemoryDb stores runs inline on the session dict — it has no
    separate runs table or legacy blob, so delete must just work."""

    def test_delete_run_does_not_leak_ghost(self):
        db = InMemoryDb()
        from agno.run.agent import RunOutput
        from agno.run.base import RunStatus
        from agno.session.agent import AgentSession

        s = AgentSession(session_id="s1", agent_id="a1", user_id="u1")
        s.upsert_run(RunOutput(run_id="r0", agent_id="a1", session_id="s1", status=RunStatus.completed))
        s.upsert_run(RunOutput(run_id="r1", agent_id="a1", session_id="s1", status=RunStatus.completed))
        db.upsert_session(s)

        db.delete_run("r0")

        assert db.get_run("r0") is None
        sess = db.get_session(session_id="s1", deserialize=False)
        assert [r["run_id"] for r in sess.get("runs") or []] == ["r1"]
