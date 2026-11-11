"""Tests for the v3.0.0 runs-table migration: legacy fallback, partial state, cleanup."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile

import pytest

from agno.db.base import SessionType
from agno.db.migrations.manager import MigrationManager
from agno.db.sqlite import SqliteDb
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession


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
    db_file = os.path.join(tempfile.mkdtemp(), "test.db")
    return SqliteDb(db_file=db_file), db_file


def _add_legacy_runs_column(db_file: str) -> None:
    """Re-add the legacy `runs` column to agno_sessions (post-fresh-schema)."""
    conn = sqlite3.connect(db_file)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_sessions)").fetchall()}
        if "runs" not in cols:
            conn.execute("ALTER TABLE agno_sessions ADD COLUMN runs JSON")
        # Make the migration manager think we're on v2.5.6 so up() will run
        conn.execute("UPDATE agno_schema_versions SET version='2.5.6' WHERE table_name='agno_sessions'")
        conn.commit()
    finally:
        conn.close()


def _insert_legacy_session(db_file: str, session_id: str, runs: list[dict], double_encoded: bool = False) -> None:
    """Insert a v2-shaped session row.

    ``double_encoded`` reproduces what v2 SQLite actually wrote: the adapter
    dumped `runs` to a string and handed it to a JSON column, which dumped it
    again. Postgres never did this, which is why the migration only loses runs
    on SQLite.
    """
    blob = json.dumps(runs)
    if double_encoded:
        blob = json.dumps(blob)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO agno_sessions (session_id, session_type, agent_id, user_id, runs, created_at) "
            "VALUES (?, 'agent', 'agent-1', 'u1', ?, 1700000000)",
            (session_id, blob),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 1: Fresh schema (no legacy column)
# ---------------------------------------------------------------------------


def test_fresh_schema_round_trip():
    """A v3-only install has no legacy column and runs go through the runs table."""
    db, db_file = _new_db()

    session = AgentSession(session_id="s1", agent_id="agent-1", user_id="u1")
    r1 = _make_run("r1", "s1", "one")
    r2 = _make_run("r2", "s1", "two")
    session.upsert_run(r1)
    session.upsert_run(r2)
    db.upsert_session(session)
    db.upsert_run(run=r1, session_id="s1", user_id="u1", run_index=0)
    db.upsert_run(run=r2, session_id="s1", user_id="u1", run_index=1)

    conn = sqlite3.connect(db_file)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_sessions)").fetchall()}
        assert "runs" not in cols, "fresh schema should not have a runs column"
        count = conn.execute("SELECT COUNT(*) FROM agno_runs WHERE session_id='s1'").fetchone()[0]
        assert count == 2
    finally:
        conn.close()

    loaded = db.get_session("s1", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r1", "r2"]


# ---------------------------------------------------------------------------
# Case 2: Legacy-blob session, never migrated → reads return all runs from blob
# ---------------------------------------------------------------------------


def test_legacy_blob_fallback_on_read():
    db, db_file = _new_db()
    # Establish the schema (no runs col), then re-add the legacy col to simulate a v2.x DB
    AgentSession(session_id="seed", agent_id="agent-1", user_id="u1")  # touch class
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run(f"r{i}", "s2", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db_file, "s2", runs)

    # Fresh adapter so the sessions table is re-reflected with the legacy column
    db = SqliteDb(db_file=db_file)
    loaded = db.get_session("s2", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]


# ---------------------------------------------------------------------------
# Case 3: Old session continues — new run is persisted, all history follows
# ---------------------------------------------------------------------------


def test_continue_legacy_session_writes_all_runs_to_table():
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run(f"r{i}", "s3", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db_file, "s3", runs)

    db = SqliteDb(db_file=db_file)
    loaded = db.get_session("s3", SessionType.AGENT)
    assert len(loaded.runs) == 2

    # Append a new run and save the session row; runs are persisted individually
    # via upsert_run (the new v3 contract).
    new_run = _make_run("r2", "s3", "fresh")
    loaded.upsert_run(new_run)
    db.upsert_session(loaded)
    for idx, r in enumerate(loaded.runs):
        db.upsert_run(run=r, session_id="s3", user_id="u1", run_index=idx)

    conn = sqlite3.connect(db_file)
    try:
        # All 3 runs (2 legacy + 1 new) are in the runs table
        ids = [
            r[0]
            for r in conn.execute("SELECT run_id FROM agno_runs WHERE session_id='s3' ORDER BY run_index").fetchall()
        ]
        assert ids == ["r0", "r1", "r2"]
        # Option A: the legacy blob is intentionally preserved as a frozen backup — writes
        # never null it. Only cleanup_legacy_runs_column() reclaims it.
        blob = conn.execute("SELECT runs FROM agno_sessions WHERE session_id='s3'").fetchone()[0]
        assert blob is not None
    finally:
        conn.close()

    # Re-read — runs come from the table (merged with the preserved blob, deduped by
    # run_id), full history preserved with no duplicates.
    reloaded = db.get_session("s3", SessionType.AGENT)
    assert [r.run_id for r in reloaded.runs] == ["r0", "r1", "r2"]


def test_upgrade_without_migration_preserves_runs_on_write():
    """Option A regression for the upgrade-without-migration data loss.

    A user upgrades to v3 code against a pre-v3 DB but does NOT run the migration,
    then continues an existing conversation. Before the fix, upsert_session nulled
    the legacy `runs` blob on write, so the historical runs (which only lived in the
    blob) were permanently lost. Now the blob is preserved as a frozen backup and the
    history survives.
    """
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    legacy = [_make_run(f"r{i}", "s9", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db_file, "s9", legacy)

    db = SqliteDb(db_file=db_file)
    # Read works via the legacy-blob fallback even though the migration never ran.
    loaded = db.get_session("s9", SessionType.AGENT)
    assert [r.run_id for r in loaded.runs] == ["r0", "r1", "r2"]

    # Continue the conversation: save a new run + the session row (the v3 save contract).
    new_run = _make_run("r3", "s9", "fresh")
    loaded.upsert_run(new_run)
    db.upsert_run(run=new_run, session_id="s9", user_id="u1", run_index=3)
    db.upsert_session(loaded)

    # The pre-existing runs survive: legacy blob preserved + new run in the table, merged.
    conn = sqlite3.connect(db_file)
    try:
        blob = conn.execute("SELECT runs FROM agno_sessions WHERE session_id='s9'").fetchone()[0]
        assert blob is not None and len(json.loads(blob)) == 3
    finally:
        conn.close()
    reloaded = db.get_session("s9", SessionType.AGENT)
    assert [r.run_id for r in reloaded.runs] == ["r0", "r1", "r2", "r3"]


# ---------------------------------------------------------------------------
# Case 4: Partial state — some runs in the table, others still in the blob
# ---------------------------------------------------------------------------


def test_partial_state_merges_table_and_blob():
    """If a session has SOME runs in the table and OTHERS still in the legacy blob
    (e.g. migration interrupted), the read merges both by run_id without losing data.
    """
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    # Ensure the runs table exists before raw-inserting into it.
    db._get_table(table_type="runs", create_table_if_not_found=True)
    _add_legacy_runs_column(db_file)

    legacy = [_make_run(f"rl{i}", "s4", f"c{i}").to_dict() for i in range(3)]
    _insert_legacy_session(db_file, "s4", legacy)

    # Hand-insert only one of those three runs into agno_runs (simulating a half-finished migration)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO agno_runs (run_id, session_id, run_type, agent_id, user_id, status, "
            "run_index, run_data, created_at, updated_at) "
            "VALUES ('rl1', 's4', 'agent', 'agent-1', 'u1', 'COMPLETED', 1, ?, 1700000000, 1700000000)",
            (json.dumps(legacy[1]),),
        )
        conn.commit()
    finally:
        conn.close()

    db = SqliteDb(db_file=db_file)
    loaded = db.get_session("s4", SessionType.AGENT)

    # All three runs must be reachable — the one in the runs table plus the two only in the blob
    assert {r.run_id for r in loaded.runs} == {"rl0", "rl1", "rl2"}, [r.run_id for r in loaded.runs]


def test_partial_state_table_wins_over_blob_on_conflict():
    """When the same run_id exists in both, the runs table is the source of truth."""
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    # Ensure the runs table exists before raw-inserting into it.
    db._get_table(table_type="runs", create_table_if_not_found=True)
    _add_legacy_runs_column(db_file)

    # Legacy blob has content="legacy-version"
    blob_run = _make_run("rx", "s5", "legacy-version").to_dict()
    _insert_legacy_session(db_file, "s5", [blob_run])

    # Runs table has content="table-version" for the SAME run_id
    table_run = _make_run("rx", "s5", "table-version").to_dict()
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO agno_runs (run_id, session_id, run_type, agent_id, user_id, status, "
            "run_index, run_data, created_at, updated_at) "
            "VALUES ('rx', 's5', 'agent', 'agent-1', 'u1', 'COMPLETED', 0, ?, 1700000000, 1700000000)",
            (json.dumps(table_run),),
        )
        conn.commit()
    finally:
        conn.close()

    db = SqliteDb(db_file=db_file)
    loaded = db.get_session("s5", SessionType.AGENT)
    assert len(loaded.runs) == 1
    assert loaded.runs[0].content == "table-version"


# ---------------------------------------------------------------------------
# Case 5: v3.0.0 migration copies runs and leaves the column intact
# ---------------------------------------------------------------------------


def test_v3_migration_is_non_destructive():
    """The migration copies runs into the runs table but preserves the legacy column."""
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run(f"r{i}", "s6", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db_file, "s6", runs)

    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up())

    conn = sqlite3.connect(db_file)
    try:
        # Runs were copied
        count = conn.execute("SELECT COUNT(*) FROM agno_runs WHERE session_id='s6'").fetchone()[0]
        assert count == 2

        # Legacy column still exists
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_sessions)").fetchall()}
        assert "runs" in cols, "migration must NOT drop the legacy column"

        # And it still holds the original data (not nulled by the migration itself)
        blob = conn.execute("SELECT runs FROM agno_sessions WHERE session_id='s6'").fetchone()[0]
        assert blob is not None
    finally:
        conn.close()


def test_v3_migration_reads_the_double_encoded_v2_blob():
    """The blob v2 SQLite really wrote must migrate, not silently copy zero runs.

    A single json.loads leaves a str, which is truthy, so the row loop iterates
    characters and every one is skipped as "not a dict" — no rows, no error.
    """
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run(f"r{i}", "s8", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db_file, "s8", runs, double_encoded=True)

    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up())

    conn = sqlite3.connect(db_file)
    try:
        run_ids = [r[0] for r in conn.execute("SELECT run_id FROM agno_runs WHERE session_id='s8'").fetchall()]
        assert sorted(run_ids) == ["r0", "r1"]

        # Stored as a real object, so json_extract-based queries (metrics) can read into it
        extracted = conn.execute(
            "SELECT json_extract(run_data, '$.run_id') FROM agno_runs WHERE session_id='s8'"
        ).fetchall()
        assert sorted(e[0] for e in extracted) == ["r0", "r1"], "run_data must be a JSON object, not a JSON string"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Case 6 + 7: cleanup_legacy_runs_column safety + happy path
# ---------------------------------------------------------------------------


def test_cleanup_refuses_when_legacy_runs_still_present():
    """cleanup_legacy_runs_column must refuse if any session still has non-null runs."""
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run("r1", "s7", "x").to_dict()]
    _insert_legacy_session(db_file, "s7", runs)

    db = SqliteDb(db_file=db_file)

    with pytest.raises(RuntimeError, match="Refusing to drop"):
        db.cleanup_legacy_runs_column()

    # Force=True bypasses the safety check
    assert db.cleanup_legacy_runs_column(force=True) is True


def test_cleanup_after_migration_requires_force():
    """Option A: writes never null the legacy column, so after migration the blob stays
    as a frozen backup. Non-force cleanup refuses (it can't tell migrated-preserved from
    un-migrated); force=True is the explicit "I've verified the migration" opt-in.
    """
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run("r1", "s8", "x").to_dict()]
    _insert_legacy_session(db_file, "s8", runs)

    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up())

    # Touching the session no longer nulls the legacy column (frozen backup).
    session = db.get_session("s8", SessionType.AGENT)
    db.upsert_session(session)
    conn = sqlite3.connect(db_file)
    try:
        blob = conn.execute("SELECT runs FROM agno_sessions WHERE session_id='s8'").fetchone()[0]
        assert blob is not None
    finally:
        conn.close()

    # Non-force cleanup refuses while any legacy blob is still present.
    with pytest.raises(RuntimeError, match="Refusing to drop"):
        db.cleanup_legacy_runs_column()

    # force=True reclaims the column after the migration copied everything into agno_runs.
    assert db.cleanup_legacy_runs_column(force=True) is True

    conn = sqlite3.connect(db_file)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_sessions)").fetchall()}
        # SQLite may or may not support DROP COLUMN depending on version; in either case
        # the cleanup helper returns True and the column (if still there) must be empty.
        if "runs" in cols:
            blob = conn.execute("SELECT runs FROM agno_sessions WHERE runs IS NOT NULL").fetchone()
            assert blob is None
    finally:
        conn.close()


def test_cleanup_is_idempotent_when_no_legacy_column():
    """Running cleanup on a fresh schema (no legacy column) is a safe no-op."""
    db, _ = _new_db()
    # Force a fresh sessions table to exist (no runs column)
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))

    assert db.cleanup_legacy_runs_column() is False


def test_down_then_up_in_the_same_process():
    """A revert drops agno_runs; a later up() in the same process must rebuild it despite stale db.metadata."""
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run(f"r{i}", "s8", f"c{i}").to_dict() for i in range(2)]
    _insert_legacy_session(db_file, "s8", runs)

    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up())
    asyncio.run(MigrationManager(db).down(target_version="2.5.6"))
    asyncio.run(MigrationManager(db).up())

    conn = sqlite3.connect(db_file)
    try:
        count = conn.execute("SELECT COUNT(*) FROM agno_runs WHERE session_id='s8'").fetchone()[0]
        assert count == 2
    finally:
        conn.close()
