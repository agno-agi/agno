"""Search decoded session names in both current and legacy SQLite rows."""

import inspect
import json
import sqlite3
from contextlib import closing

import pytest
import pytest_asyncio

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.db.sqlite.async_sqlite import AsyncSqliteDb
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession

pytestmark = pytest.mark.asyncio


async def _resolve(result):
    """Exercise the same assertions against sync and async database methods."""
    return await result if inspect.isawaitable(result) else result


@pytest_asyncio.fixture(params=[SqliteDb, AsyncSqliteDb], ids=["sync", "async"])
async def sqlite_db(request, tmp_path):
    db_file = str(tmp_path / "sessions.db")
    db = request.param(db_file=db_file)
    try:
        yield db, db_file
    finally:
        await _resolve(db.db_engine.dispose())


async def _store_session(sqlite_db, session, legacy=False):
    db, db_file = sqlite_db
    assert await _resolve(db.upsert_session(session)) is not None
    if legacy:
        # Older adapters encoded JSON fields twice before writing them.
        with closing(sqlite3.connect(db_file)) as conn, conn:
            conn.execute(
                "UPDATE agno_sessions SET session_data = ? WHERE session_id = ?",
                (json.dumps(json.dumps(session.session_data)), session.session_id),
            )


@pytest.mark.parametrize(
    ("name", "query"),
    [
        pytest.param("中文会话", "中文", id="unicode"),
        pytest.param('Say "hello" today', '"hello"', id="quotes"),
        pytest.param(r"Notes in C:\work\notes", r"C:\work", id="backslash"),
        pytest.param("Project Alpha", "aLPHa", id="ascii-case-insensitive-substring"),
    ],
)
async def test_search_decodes_names_in_mixed_storage_formats(sqlite_db, name, query):
    db, _ = sqlite_db
    await _store_session(sqlite_db, AgentSession(session_id="current", session_data={"session_name": name}))
    await _store_session(
        sqlite_db,
        AgentSession(session_id="legacy", session_data={"session_name": name}),
        legacy=True,
    )

    sessions, total = await _resolve(
        db.get_sessions(session_type=SessionType.AGENT, session_name=query, deserialize=False)
    )

    assert {session["session_id"] for session in sessions} == {"current", "legacy"}
    assert total == 2
    assert all(session["session_data"]["session_name"] == name for session in sessions)


@pytest.mark.parametrize(
    ("session_type", "session_class"),
    [
        pytest.param(SessionType.AGENT, AgentSession, id="agent"),
        pytest.param(SessionType.TEAM, TeamSession, id="team"),
        pytest.param(SessionType.WORKFLOW, WorkflowSession, id="workflow"),
    ],
)
async def test_search_matches_only_top_level_session_name(sqlite_db, session_type, session_class):
    db, _ = sqlite_db
    await _store_session(sqlite_db, session_class(session_id="match", session_data={"session_name": "Needle chat"}))
    await _store_session(
        sqlite_db,
        session_class(
            session_id="state-only",
            session_data={"session_name": "Unrelated", "session_state": {"note": "needle"}},
        ),
    )
    await _store_session(
        sqlite_db,
        session_class(
            session_id="legacy-state-only",
            session_data={"session_name": "Unrelated", "session_state": {"session_name": "needle"}},
        ),
        legacy=True,
    )

    sessions = await _resolve(db.get_sessions(session_type=session_type, session_name="needle"))

    assert [session.session_id for session in sessions] == ["match"]
    assert isinstance(sessions[0], session_class)


async def test_search_filters_before_counting_and_paginating(sqlite_db):
    db, _ = sqlite_db
    rows = [
        ("first", {"session_name": "Needle one"}, False),
        ("state-only", {"session_name": "Unrelated", "session_state": {"note": "needle"}}, False),
        ("second", {"session_name": "Needle two"}, True),
        ("missing-name", {"session_state": {"note": "needle"}}, True),
        ("third", {"session_name": "Needle three"}, False),
    ]
    for created_at, (session_id, session_data, legacy) in enumerate(rows, start=1):
        await _store_session(
            sqlite_db,
            AgentSession(session_id=session_id, session_data=session_data, created_at=created_at),
            legacy=legacy,
        )

    sessions, total = await _resolve(
        db.get_sessions(
            session_name="needle",
            limit=1,
            page=2,
            sort_by="created_at",
            sort_order="asc",
            deserialize=False,
        )
    )

    assert total == 3
    assert [session["session_id"] for session in sessions] == ["second"]


@pytest.mark.parametrize("legacy", [False, True], ids=["current", "legacy"])
@pytest.mark.parametrize(
    ("query", "expected_ids"),
    [
        pytest.param(None, {"missing", "null", "empty", "named"}, id="no-filter"),
        pytest.param("", {"missing", "null", "empty", "named"}, id="empty-query"),
        pytest.param("null", set(), id="null-is-not-a-name"),
        pytest.param("session_name", set(), id="json-keys-are-not-names"),
    ],
)
async def test_search_handles_missing_null_and_empty_names(sqlite_db, legacy, query, expected_ids):
    db, _ = sqlite_db
    rows = [
        ("missing", {}),
        ("null", {"session_name": None}),
        ("empty", {"session_name": ""}),
        ("named", {"session_name": "Named"}),
    ]
    for session_id, session_data in rows:
        await _store_session(
            sqlite_db,
            AgentSession(session_id=session_id, session_data=session_data),
            legacy=legacy,
        )

    sessions, total = await _resolve(db.get_sessions(session_name=query, deserialize=False))

    assert {session["session_id"] for session in sessions} == expected_ids
    assert total == len(expected_ids)
