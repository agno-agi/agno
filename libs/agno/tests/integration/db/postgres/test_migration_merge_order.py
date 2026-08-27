"""End-to-end regression test for reviewer comment #2 on PR #8350.

Scenario the reviewer flagged: after the v3 migration runs but before
``cleanup_legacy_runs_column()`` is called, a session's runs live in **both**
the ``agno_runs`` table and the legacy ``agno_sessions.runs`` JSONB column.
Reads must merge the two surfaces while preserving the true chronological
insertion order — even when only *some* runs made it into the runs table.

This test runs against a real Postgres (docker: pgvector on :5532). It seeds a
v2 blob, runs the actual v3 migration, then simulates a partial-migration
state by removing a subset of runs from the ``agno_runs`` table. We read the
runs table + legacy blob directly and feed them through the same
``merge_runs_table_with_legacy_blob`` helper the adapter's read path uses, and
assert the merged order is (r0, r1, r2, r3) — not the buggy (r0, r2, r1, r3)
the old implementation produced.

(We exercise the merge helper directly rather than going through
``get_session()`` because the v3 ORM schema no longer surfaces the legacy
``runs`` column; the merge helper is what the reviewer's comment #2 is
actually about.)
"""

from __future__ import annotations

import json
import time
from typing import List

import pytest
from sqlalchemy import text

from agno.db.migrations.versions import v3_0_0
from agno.db.postgres.postgres import PostgresDb
from agno.db.utils import merge_runs_table_with_legacy_blob

SESSION_ID = "merge-order-e2e"
USER_ID = "e2e-user"
AGENT_ID = "e2e-agent"


@pytest.fixture(autouse=True)
def cleanup_e2e_tables(postgres_db_real: PostgresDb):
    """Drop test session + runs rows before AND after each test — the test
    seeds raw SQL, so we can't rely on ORM-level cleanup."""

    def _wipe():
        for table in ("test_sessions", postgres_db_real.runs_table_name):
            with postgres_db_real.Session() as sess:
                try:
                    sess.execute(
                        text(f"DELETE FROM test_schema.{table} WHERE session_id = :sid"),
                        {"sid": SESSION_ID},
                    )
                    sess.commit()
                except Exception:
                    # Table may not exist yet — that's fine for pre-test wipe.
                    sess.rollback()

    _wipe()
    yield
    _wipe()


def _build_v2_runs_blob(run_ids: List[str]) -> str:
    """Build a JSON blob shaped like a v2.x ``agno_sessions.runs`` column."""
    now = int(time.time())
    return json.dumps(
        [
            {
                "run_id": rid,
                "agent_id": AGENT_ID,
                "session_id": SESSION_ID,
                "user_id": USER_ID,
                "status": "COMPLETED",
                "created_at": now + i,
                "content": f"content-{rid}",
                "messages": [
                    {"role": "user", "content": f"q-{rid}"},
                    {"role": "assistant", "content": f"a-{rid}"},
                ],
            }
            for i, rid in enumerate(run_ids)
        ]
    )


def _seed_v2_session(postgres_db_real: PostgresDb, run_ids: List[str]) -> None:
    """Insert a v2-shaped session row directly, bypassing the ORM helpers so
    the ``runs`` column really carries the whole history as a JSONB blob."""
    postgres_db_real._get_table("sessions", create_table_if_not_found=True)

    # The current schema is v3 (no `runs` column). Re-add it so we can seed a
    # v2.x-shaped row, exactly as an unmigrated production DB would look.
    with postgres_db_real.Session() as sess:
        sess.execute(text("ALTER TABLE test_schema.test_sessions ADD COLUMN IF NOT EXISTS runs jsonb"))
        sess.commit()

    now = int(time.time())
    with postgres_db_real.Session() as sess:
        sess.execute(
            text(
                """
                INSERT INTO test_schema.test_sessions
                (session_id, session_type, agent_id, user_id, runs, created_at, updated_at)
                VALUES (:sid, 'agent', :aid, :uid, CAST(:runs AS jsonb), :now, :now)
                """
            ),
            {
                "sid": SESSION_ID,
                "aid": AGENT_ID,
                "uid": USER_ID,
                "runs": _build_v2_runs_blob(run_ids),
                "now": now,
            },
        )
        sess.commit()


def _delete_runs_from_table(postgres_db_real: PostgresDb, run_ids: List[str]) -> None:
    """Simulate a partial migration: after v3 migration copies everything, some
    rows never made it (e.g. adapter crash mid-copy, retry hole) — the legacy
    blob remains the only source of truth for those runs."""
    if not run_ids:
        return
    with postgres_db_real.Session() as sess:
        sess.execute(
            text(f"DELETE FROM test_schema.{postgres_db_real.runs_table_name} WHERE run_id = ANY(:rids)"),
            {"rids": run_ids},
        )
        sess.commit()


def _get_runs_table_ids(postgres_db_real: PostgresDb) -> List[str]:
    with postgres_db_real.Session() as sess:
        rows = sess.execute(
            text(
                f"SELECT run_id FROM test_schema.{postgres_db_real.runs_table_name} "
                "WHERE session_id = :sid ORDER BY run_index"
            ),
            {"sid": SESSION_ID},
        ).fetchall()
    return [r[0] for r in rows]


def _get_legacy_blob_ids(postgres_db_real: PostgresDb) -> List[str]:
    with postgres_db_real.Session() as sess:
        row = sess.execute(
            text("SELECT runs FROM test_schema.test_sessions WHERE session_id = :sid"),
            {"sid": SESSION_ID},
        ).fetchone()
    if not row or not row[0]:
        return []
    runs = row[0] if isinstance(row[0], list) else json.loads(row[0])
    return [r["run_id"] for r in runs]


def _read_merged_runs(postgres_db_real: PostgresDb) -> List[dict]:
    """Read the runs table + the legacy blob and merge them exactly as the
    adapter would on the read path. Comment #2 is about the merge helper's
    ordering behavior, so we exercise it against real DB state without relying
    on the ORM schema surfacing the (legacy) ``runs`` column."""
    with postgres_db_real.Session() as sess:
        table_rows = sess.execute(
            text(
                f"SELECT run_data FROM test_schema.{postgres_db_real.runs_table_name} "
                "WHERE session_id = :sid ORDER BY run_index"
            ),
            {"sid": SESSION_ID},
        ).fetchall()
        table_runs = [r[0] for r in table_rows]

        blob_row = sess.execute(
            text("SELECT runs FROM test_schema.test_sessions WHERE session_id = :sid"),
            {"sid": SESSION_ID},
        ).fetchone()
        legacy_runs = blob_row[0] if blob_row else None

    return merge_runs_table_with_legacy_blob(table_runs, legacy_runs)


class TestPartialMigrationMergeOrder:
    """Reviewer comment #2 — merge must preserve chronological insertion order."""

    def test_split_odd_migrated_returns_full_chronological_order(self, postgres_db_real: PostgresDb):
        """r0 and r2 remain in the runs table; r1 and r3 exist only in the
        legacy blob. get_session() must return [r0, r1, r2, r3]."""
        _seed_v2_session(postgres_db_real, ["r0", "r1", "r2", "r3"])

        migrated = v3_0_0._migrate_postgres(postgres_db_real, "sessions", "test_sessions")
        assert migrated is True

        assert set(_get_runs_table_ids(postgres_db_real)) == {"r0", "r1", "r2", "r3"}
        assert _get_legacy_blob_ids(postgres_db_real) == ["r0", "r1", "r2", "r3"]

        _delete_runs_from_table(postgres_db_real, ["r1", "r3"])
        assert set(_get_runs_table_ids(postgres_db_real)) == {"r0", "r2"}

        merged = _read_merged_runs(postgres_db_real)
        run_ids = [r["run_id"] for r in merged]

        assert run_ids == ["r0", "r1", "r2", "r3"], (
            f"chronological order broken — got {run_ids}. "
            "The old merge would have returned ['r0', 'r2', 'r1', 'r3'] here."
        )

    def test_leading_run_only_in_table(self, postgres_db_real: PostgresDb):
        """Only r0 in the runs table; r1, r2, r3 in blob only."""
        _seed_v2_session(postgres_db_real, ["r0", "r1", "r2", "r3"])
        v3_0_0._migrate_postgres(postgres_db_real, "sessions", "test_sessions")
        _delete_runs_from_table(postgres_db_real, ["r1", "r2", "r3"])

        merged = _read_merged_runs(postgres_db_real)
        run_ids = [r["run_id"] for r in merged]
        assert run_ids == ["r0", "r1", "r2", "r3"]

    def test_trailing_run_only_in_table(self, postgres_db_real: PostgresDb):
        """Only r3 in the runs table; r0, r1, r2 in blob only."""
        _seed_v2_session(postgres_db_real, ["r0", "r1", "r2", "r3"])
        v3_0_0._migrate_postgres(postgres_db_real, "sessions", "test_sessions")
        _delete_runs_from_table(postgres_db_real, ["r0", "r1", "r2"])

        merged = _read_merged_runs(postgres_db_real)
        run_ids = [r["run_id"] for r in merged]
        assert run_ids == ["r0", "r1", "r2", "r3"]

    def test_fresh_run_added_post_migration_appears_at_tail(self, postgres_db_real: PostgresDb):
        """A run written directly to the runs table AFTER migration (with no
        counterpart in the legacy blob) is by definition newer than everything
        the blob knew about — it should appear at the tail."""
        _seed_v2_session(postgres_db_real, ["r0", "r1"])
        v3_0_0._migrate_postgres(postgres_db_real, "sessions", "test_sessions")

        with postgres_db_real.Session() as sess:
            sess.execute(
                text(
                    f"""
                    INSERT INTO test_schema.{postgres_db_real.runs_table_name}
                    (run_id, session_id, run_type, agent_id, user_id, status, run_index, run_data, created_at, updated_at)
                    VALUES (:rid, :sid, 'agent', :aid, :uid, 'COMPLETED', 2, CAST(:data AS jsonb), :now, :now)
                    """
                ),
                {
                    "rid": "r2",
                    "sid": SESSION_ID,
                    "aid": AGENT_ID,
                    "uid": USER_ID,
                    "data": json.dumps({"run_id": "r2", "content": "post-migration"}),
                    "now": int(time.time()),
                },
            )
            sess.commit()

        merged = _read_merged_runs(postgres_db_real)
        run_ids = [r["run_id"] for r in merged]
        assert run_ids == ["r0", "r1", "r2"]

    def test_conflict_between_table_and_blob_uses_table_at_legacy_position(self, postgres_db_real: PostgresDb):
        """When the same run_id exists in both surfaces, the table wins on
        *content* but the legacy blob's position wins on *order*."""
        _seed_v2_session(postgres_db_real, ["r0", "r1", "r2"])
        v3_0_0._migrate_postgres(postgres_db_real, "sessions", "test_sessions")

        with postgres_db_real.Session() as sess:
            sess.execute(
                text(
                    f"UPDATE test_schema.{postgres_db_real.runs_table_name} "
                    "SET run_data = jsonb_set(run_data, '{content}', '\"table-fresh\"'::jsonb) "
                    "WHERE run_id = 'r1'"
                )
            )
            sess.commit()

        merged = _read_merged_runs(postgres_db_real)
        run_ids = [r["run_id"] for r in merged]
        assert run_ids == ["r0", "r1", "r2"], "position must come from the legacy blob"

        r1 = next(r for r in merged if r["run_id"] == "r1")
        assert r1.get("content") == "table-fresh", "content must come from the runs table"
