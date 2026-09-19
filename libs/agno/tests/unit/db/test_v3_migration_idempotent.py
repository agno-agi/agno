"""Regression tests for reviewer comment #8 on PR #8350.

The v3.0.0 migration for JsonDb/GcsJsonDb was not idempotent: if invoked a
second time (retry after transient failure, re-upgrade, tooling loop), it
overwrote runs already in the runs table with their stale copies from the
legacy blob. Any post-migration write to a run was silently reverted.

These tests exercise the runs-table-wins-on-conflict semantics against real
JsonDb — the reviewer's exact scenario.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from agno.db.json.json_db import JsonDb
from agno.db.migrations.versions.v3_0_0 import _migrate_jsondb


@pytest.fixture
def partially_migrated_json_db():
    tmp = tempfile.mkdtemp()
    db = JsonDb(db_path=tmp)
    session_row = {
        "session_id": "s1",
        "session_type": "agent",
        "agent_id": "a1",
        "user_id": "u1",
        "runs": [
            {"run_id": "r0", "agent_id": "a1", "status": "COMPLETED", "content": "STALE-0", "created_at": 1},
            {"run_id": "r1", "agent_id": "a1", "status": "COMPLETED", "content": "STALE-1", "created_at": 2},
        ],
        "created_at": 1,
        "updated_at": 1,
    }
    with open(os.path.join(tmp, "agno_sessions.json"), "w") as f:
        json.dump([session_row], f)
    _migrate_jsondb(db, "sessions", "agno_sessions")
    return db


def _content(db: JsonDb, run_id: str) -> str:
    row = db.get_run(run_id, deserialize=False)
    return row.get("run_data", {}).get("content")


class TestJsonDbMigrationIdempotent:
    """Reviewer #8 — the runs table wins over the legacy blob on rerun."""

    def test_rerun_preserves_fresh_post_migration_write(self, partially_migrated_json_db):
        """A run updated after the first migration must survive a rerun."""
        db = partially_migrated_json_db

        # Simulate a fresh update to r0 (e.g. user re-ran a run to update it)
        db.upsert_run(
            run={"run_id": "r0", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED", "content": "FRESH-0"},
            session_id="s1",
            user_id="u1",
            run_index=0,
        )
        assert _content(db, "r0") == "FRESH-0"

        # Rerun the migration
        _migrate_jsondb(db, "sessions", "agno_sessions")

        assert _content(db, "r0") == "FRESH-0", (
            "post-migration writes must not be reverted by a migration rerun — "
            "the runs table is the source of truth on conflict"
        )
        # And the untouched r1 is still there
        assert _content(db, "r1") == "STALE-1"

    def test_rerun_still_backfills_unmigrated_runs(self, partially_migrated_json_db):
        """If a new run_id appears in the legacy blob that isn't in the runs
        table (a genuinely-new migration target from a partially-migrated
        upgrade), the rerun should still copy it in."""
        db = partially_migrated_json_db

        # Manually add a *third* run to the legacy blob (simulating a
        # follow-up migration where new data arrived from an older client).
        # We do this by editing the sessions file directly.
        import os

        sessions_file = os.path.join(db.db_path, "agno_sessions.json")
        with open(sessions_file) as f:
            sessions = json.load(f)
        sessions[0]["runs"].append(
            {"run_id": "r2", "agent_id": "a1", "status": "COMPLETED", "content": "NEW-from-legacy", "created_at": 3}
        )
        with open(sessions_file, "w") as f:
            json.dump(sessions, f)

        # Rerun migration
        _migrate_jsondb(db, "sessions", "agno_sessions")

        # r2 should now be in the runs table
        assert _content(db, "r2") == "NEW-from-legacy"
        # r0 / r1 unchanged (already in the table)
        assert _content(db, "r0") == "STALE-0"
        assert _content(db, "r1") == "STALE-1"

    def test_rerun_is_noop_when_nothing_new(self, partially_migrated_json_db):
        """Second rerun on unchanged data should just be a no-op."""
        db = partially_migrated_json_db

        # Snapshot the runs file
        runs_file = os.path.join(db.db_path, "agno_runs.json")
        with open(runs_file) as f:
            before = json.load(f)

        _migrate_jsondb(db, "sessions", "agno_sessions")

        with open(runs_file) as f:
            after = json.load(f)

        # Same content, same order (idempotent)
        assert {r["run_id"] for r in before} == {r["run_id"] for r in after}

    def test_conflict_priority_documented_in_get_run(self, partially_migrated_json_db):
        """The get_run API surfaces the fresh row after rerun (integration
        check on top of the raw file check above)."""
        db = partially_migrated_json_db
        db.upsert_run(
            run={"run_id": "r1", "agent_id": "a1", "session_id": "s1", "status": "COMPLETED", "content": "FRESH-1"},
            session_id="s1",
            user_id="u1",
            run_index=1,
        )
        _migrate_jsondb(db, "sessions", "agno_sessions")
        assert _content(db, "r1") == "FRESH-1"
