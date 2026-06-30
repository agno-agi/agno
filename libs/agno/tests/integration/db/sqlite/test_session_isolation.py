"""Integration tests for session user_id isolation in SqliteDb.

Mirrors the Postgres isolation tests to verify the same security
boundaries hold across different SQL backends.
"""

import time

import pytest

from agno.db.base import SessionType
from agno.db.sqlite.sqlite import SqliteDb
from agno.session.agent import AgentSession


@pytest.fixture(autouse=True)
def cleanup_sessions(sqlite_db_real: SqliteDb):
    yield

    with sqlite_db_real.Session() as session:
        try:
            sessions_table = sqlite_db_real._get_table("sessions", create_table_if_not_found=True)
            if sessions_table is not None:
                session.execute(sessions_table.delete())
            session.commit()
        except Exception:
            session.rollback()


def _make_session(session_id: str, user_id: str) -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id="test_agent",
        user_id=user_id,
        session_data={"session_name": f"Session {session_id}"},
        created_at=int(time.time()),
    )


# -- delete_session isolation --


def test_delete_session_correct_user(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.delete_session("s1", user_id="alice")
    assert result is True

    session = sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is None


def test_delete_session_wrong_user(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.delete_session("s1", user_id="bob")
    assert result is False

    session = sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is not None
    assert session.user_id == "alice"


def test_delete_session_wildcard(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.delete_session("s1", user_id=None)
    assert result is True

    assert sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is None


def test_delete_session_empty_string(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.delete_session("s1", user_id="")
    assert result is False

    assert sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is not None


# -- delete_sessions isolation --


def test_delete_sessions_correct_user(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))
    sqlite_db_real.upsert_session(_make_session("s2", "alice"))
    sqlite_db_real.upsert_session(_make_session("s3", "bob"))

    sqlite_db_real.delete_sessions(["s1", "s2", "s3"], user_id="alice")

    assert sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is None
    assert sqlite_db_real.get_session(session_id="s2", session_type=SessionType.AGENT) is None

    bob_session = sqlite_db_real.get_session(session_id="s3", session_type=SessionType.AGENT)
    assert bob_session is not None
    assert bob_session.user_id == "bob"


def test_delete_sessions_wrong_user(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    sqlite_db_real.delete_sessions(["s1"], user_id="eve")

    assert sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is not None


def test_delete_sessions_wildcard(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))
    sqlite_db_real.upsert_session(_make_session("s2", "bob"))

    sqlite_db_real.delete_sessions(["s1", "s2"], user_id=None)

    assert sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is None
    assert sqlite_db_real.get_session(session_id="s2", session_type=SessionType.AGENT) is None


# -- rename_session isolation --


def test_rename_session_correct_user(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Renamed by Alice",
        user_id="alice",
    )
    assert result is not None
    assert result.session_data["session_name"] == "Renamed by Alice"


def test_rename_session_wrong_user(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Hacked",
        user_id="bob",
    )
    assert result is None

    session = sqlite_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session.session_data["session_name"] == "Session s1"


def test_rename_session_wildcard(sqlite_db_real: SqliteDb):
    sqlite_db_real.upsert_session(_make_session("s1", "alice"))

    result = sqlite_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Renamed without user",
        user_id=None,
    )
    assert result is not None
    assert result.session_data["session_name"] == "Renamed without user"
