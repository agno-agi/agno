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
    _migrate_jsondb(db, "sessions", "agno_sessions")
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
        assert "r1" not in run_ids, f"deleted r1 resurrected via legacy blob on read: got {run_ids}"
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


class TestSqliteDbDeleteRunScrubsLegacyBlob:
    """SQL parallel of the JsonDb tests. Same partial-migration state: v3 runs
    table populated, but the legacy `agno_sessions.runs` column still holds a
    backup blob. delete_run must scrub both surfaces."""

    @pytest.fixture
    def sqlite_partially_migrated(self):
        """SqliteDb with a v3 runs table AND a legacy `runs` column on
        agno_sessions carrying the pre-migration blob (as a fully-migrated
        DB would look before cleanup_legacy_runs_field(force=True))."""
        import json as _json
        import time as _time

        from sqlalchemy import MetaData, text

        from agno.db.sqlite import SqliteDb

        tmp = tempfile.mkdtemp()
        db = SqliteDb(db_file=os.path.join(tmp, "t.db"))
        db._get_table("sessions", create_table_if_not_found=True)
        db._get_table("runs", create_table_if_not_found=True)

        # Add the legacy `runs` column and plant a v2.x-shaped session with 3 runs.
        legacy = [
            {"run_id": "r0", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED", "created_at": 1},
            {"run_id": "r1", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED", "created_at": 2},
            {"run_id": "r2", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED", "created_at": 3},
        ]
        with db.Session() as sess, sess.begin():
            cols = [row[1] for row in sess.execute(text("PRAGMA table_info(agno_sessions)")).fetchall()]
            if "runs" not in cols:
                sess.execute(text("ALTER TABLE agno_sessions ADD COLUMN runs TEXT"))
            sess.execute(text("DELETE FROM agno_sessions WHERE session_id='s1'"))
            sess.execute(text("DELETE FROM agno_runs WHERE session_id='s1'"))
            now = int(_time.time())
            sess.execute(
                text(
                    "INSERT INTO agno_sessions (session_id, session_type, agent_id, user_id, agent_data, "
                    "session_data, metadata, runs, created_at, updated_at) VALUES "
                    "('s1', 'agent', 'a1', 'u1', '{}', '{}', '{}', :runs, :now, :now)"
                ),
                {"runs": _json.dumps(legacy), "now": now},
            )
            # Also populate agno_runs so the v3 side has the same data (as the
            # migration would leave it).
            for idx, r in enumerate(legacy):
                sess.execute(
                    text(
                        "INSERT INTO agno_runs (run_id, session_id, agent_id, user_id, run_type, run_index, "
                        "status, run_data, created_at, updated_at) VALUES "
                        "(:rid, 's1', 'a1', 'u1', 'agent', :idx, 'COMPLETED', :data, :now, :now)"
                    ),
                    {"rid": r["run_id"], "idx": idx, "data": _json.dumps(r), "now": now},
                )

        # Refresh SQLAlchemy metadata so the read path sees the legacy column.
        db.metadata = MetaData()
        db.metadata.reflect(bind=db.db_engine)
        if hasattr(db, "_tables"):
            db._tables = {}
        # The manual ALTER above bypassed the adapter, so bust its resolution cache too
        db._table_cache.clear()

        return db

    def test_delete_run_scrubs_legacy_blob(self, sqlite_partially_migrated):
        """The single-delete path must remove the run from both surfaces."""
        import json as _json

        from sqlalchemy import text

        from agno.db.base import SessionType

        db = sqlite_partially_migrated

        # Sanity: pre-delete state has all 3 runs visible via the merged read.
        loaded = db.get_session(session_id="s1", session_type=SessionType.AGENT)
        assert [r.run_id for r in (loaded.runs or [])] == ["r0", "r1", "r2"]

        assert db.delete_run("r1") is True

        # Reload after delete: r1 must not reappear via the merge helper.
        loaded = db.get_session(session_id="s1", session_type=SessionType.AGENT)
        assert [r.run_id for r in (loaded.runs or [])] == ["r0", "r2"], (
            "r1 was resurrected by the legacy blob (delete_run failed to scrub it)"
        )

        # Raw legacy column must have r1 removed.
        with db.Session() as sess:
            raw = sess.execute(text("SELECT runs FROM agno_sessions WHERE session_id='s1'")).first()
            blob = _json.loads(raw[0]) if raw and raw[0] else []
        assert [r["run_id"] for r in blob] == ["r0", "r2"]

    def test_delete_runs_bulk_scrubs_legacy_blob(self, sqlite_partially_migrated):
        """The bulk-delete path must remove all given runs from both surfaces."""
        import json as _json

        from sqlalchemy import text

        from agno.db.base import SessionType

        db = sqlite_partially_migrated

        db.delete_runs(["r0", "r2"])

        loaded = db.get_session(session_id="s1", session_type=SessionType.AGENT)
        assert [r.run_id for r in (loaded.runs or [])] == ["r1"]

        with db.Session() as sess:
            raw = sess.execute(text("SELECT runs FROM agno_sessions WHERE session_id='s1'")).first()
            blob = _json.loads(raw[0]) if raw and raw[0] else []
        assert [r["run_id"] for r in blob] == ["r1"]

    def test_scrub_helper_is_a_noop_when_legacy_column_absent(self):
        """When the sessions table has no `runs` column (fully migrated + cleanup
        run), the scrub silently returns without erroring."""
        from agno.db.sqlite import SqliteDb

        tmp = tempfile.mkdtemp()
        db = SqliteDb(db_file=os.path.join(tmp, "t.db"))
        db._get_table("sessions", create_table_if_not_found=True)
        db._get_table("runs", create_table_if_not_found=True)

        # No legacy `runs` column exists on the fresh v3 schema. The helper
        # must return cleanly without raising.
        db._scrub_run_ids_from_legacy_blob(["r0"])  # should not raise
        db._scrub_run_ids_from_legacy_blob([])  # empty list -> early return


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
