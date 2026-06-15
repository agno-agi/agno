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


def _insert_legacy_session(db_file: str, session_id: str, runs: list[dict]) -> None:
    conn = sqlite3.connect(db_file)
    try:
        conn.execute(
            "INSERT INTO agno_sessions (session_id, session_type, agent_id, user_id, runs, created_at) "
            "VALUES (?, 'agent', 'agent-1', 'u1', ?, 1700000000)",
            (session_id, json.dumps(runs)),
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
    session.upsert_run(_make_run("r1", "s1", "one"))
    session.upsert_run(_make_run("r2", "s1", "two"))
    db.upsert_session(session)

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

    # Append a new run and save
    loaded.upsert_run(_make_run("r2", "s3", "fresh"))
    db.upsert_session(loaded)

    conn = sqlite3.connect(db_file)
    try:
        # All 3 runs (2 legacy + 1 new) are in the runs table
        ids = [r[0] for r in conn.execute(
            "SELECT run_id FROM agno_runs WHERE session_id='s3' ORDER BY run_index"
        ).fetchall()]
        assert ids == ["r0", "r1", "r2"]
        # The legacy blob has been cleared for this session
        blob = conn.execute("SELECT runs FROM agno_sessions WHERE session_id='s3'").fetchone()[0]
        assert blob is None
    finally:
        conn.close()

    # Re-read — runs come from the table now, full history preserved
    reloaded = db.get_session("s3", SessionType.AGENT)
    assert [r.run_id for r in reloaded.runs] == ["r0", "r1", "r2"]


# ---------------------------------------------------------------------------
# Case 4: Partial state — some runs in the table, others still in the blob
# ---------------------------------------------------------------------------


def test_partial_state_merges_table_and_blob():
    """If a session has SOME runs in the table and OTHERS still in the legacy blob
    (e.g. migration interrupted), the read merges both by run_id without losing data.
    """
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
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


def test_cleanup_succeeds_after_migration():
    """After a normal migration + a save touches each session, cleanup should succeed."""
    db, db_file = _new_db()
    db.upsert_session(AgentSession(session_id="seed", agent_id="agent-1", user_id="u1"))
    _add_legacy_runs_column(db_file)

    runs = [_make_run("r1", "s8", "x").to_dict()]
    _insert_legacy_session(db_file, "s8", runs)

    db = SqliteDb(db_file=db_file)
    asyncio.run(MigrationManager(db).up())

    # Touch each session so the legacy column gets nulled
    for sid in ["seed", "s8"]:
        session = db.get_session(sid, SessionType.AGENT)
        if session is not None:
            db.upsert_session(session)

    assert db.cleanup_legacy_runs_column() is True

    conn = sqlite3.connect(db_file)
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(agno_sessions)").fetchall()}
        # SQLite may or may not support DROP COLUMN depending on version; in either case
        # the cleanup helper should return True and the column (if still there) must be empty.
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
