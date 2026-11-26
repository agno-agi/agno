"""A new run must sort after the session's existing rows, whatever position the caller computed.

``resolve_run_index`` hands ``upsert_run`` the run's position in the in-memory
``session.runs`` list. After runs are deleted from the front of that list (a
compaction, a redaction, ``delete_runs``), that position collides with or sorts
before rows that still exist, and ``get_session`` returns history out of order.
The adapter knows the real maximum; it should never place a new row below it.
"""

from __future__ import annotations

import sqlite3

import pytest

from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.run.agent import RunOutput
from agno.session.agent import AgentSession


def _run(run_id: str) -> RunOutput:
    return RunOutput(run_id=run_id, agent_id="a1", session_id="s1")


def _rows(db_file: str):
    con = sqlite3.connect(db_file)
    try:
        return con.execute("SELECT run_id, run_index FROM agno_runs ORDER BY run_index").fetchall()
    finally:
        con.close()


def test_new_run_lands_after_survivors_when_leading_runs_were_deleted(tmp_path):
    db_file = str(tmp_path / "t.db")
    db = SqliteDb(db_file=db_file)
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1", created_at=1000, updated_at=1000))
    for index, run_id in enumerate(["r0", "r1", "r2"]):
        db.upsert_run(_run(run_id), session_id="s1", run_index=index)

    db.delete_runs(["r0", "r1"])
    # The in-memory list is now ["r2", "r3"], so the caller computes position 1.
    db.upsert_run(_run("r3"), session_id="s1", run_index=1)

    assert _rows(db_file) == [("r2", 2), ("r3", 3)]
    assert [run.run_id for run in db.get_session("s1").runs] == ["r2", "r3"]


@pytest.mark.asyncio
async def test_async_new_run_lands_after_survivors_when_leading_runs_were_deleted(tmp_path):
    db_file = str(tmp_path / "t.db")
    db = AsyncSqliteDb(db_file=db_file)
    await db.upsert_session(AgentSession(session_id="s1", agent_id="a1", created_at=1000, updated_at=1000))
    for index, run_id in enumerate(["r0", "r1", "r2"]):
        await db.upsert_run(_run(run_id), session_id="s1", run_index=index)

    await db.delete_runs(["r0", "r1"])
    await db.upsert_run(_run("r3"), session_id="s1", run_index=1)

    assert _rows(db_file) == [("r2", 2), ("r3", 3)]
    assert [run.run_id for run in (await db.get_session("s1")).runs] == ["r2", "r3"]


def test_existing_rows_keep_their_index_on_update(tmp_path):
    db_file = str(tmp_path / "t.db")
    db = SqliteDb(db_file=db_file)
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1", created_at=1000, updated_at=1000))
    db.upsert_run(_run("r0"), session_id="s1", run_index=0)
    db.upsert_run(_run("r1"), session_id="s1", run_index=1)

    db.upsert_run(_run("r0"), session_id="s1", run_index=7)  # a status update re-sends the run

    assert _rows(db_file) == [("r0", 0), ("r1", 1)]


def test_an_explicit_higher_index_is_kept(tmp_path):
    db_file = str(tmp_path / "t.db")
    db = SqliteDb(db_file=db_file)
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1", created_at=1000, updated_at=1000))
    db.upsert_run(_run("r0"), session_id="s1", run_index=0)

    db.upsert_run(_run("r9"), session_id="s1", run_index=9)

    assert _rows(db_file) == [("r0", 0), ("r9", 9)]
