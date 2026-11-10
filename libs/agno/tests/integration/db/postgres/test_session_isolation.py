"""Integration tests for session user_id isolation in PostgresDb.

Verifies that delete_session, delete_sessions, and rename_session
correctly enforce user_id ownership when the parameter is provided.
"""

import time

import pytest

from agno.db.base import SessionType
from agno.db.postgres.postgres import PostgresDb
from agno.session.agent import AgentSession


@pytest.fixture(autouse=True)
def cleanup_sessions(postgres_db_real: PostgresDb):
    yield

    with postgres_db_real.Session() as session:
        try:
            sessions_table = postgres_db_real._get_table("sessions", create_table_if_not_found=True)
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


def test_delete_session_correct_user(postgres_db_real: PostgresDb):
    """delete_session with matching user_id succeeds."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.delete_session("s1", user_id="alice")
    assert result is True

    session = postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is None


def test_delete_session_wrong_user(postgres_db_real: PostgresDb):
    """delete_session with wrong user_id is blocked — session survives."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.delete_session("s1", user_id="bob")
    assert result is False

    session = postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is not None
    assert session.user_id == "alice"


def test_delete_session_no_user_id_wildcard(postgres_db_real: PostgresDb):
    """delete_session with user_id=None is a wildcard — deletes any user's session."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.delete_session("s1", user_id=None)
    assert result is True

    session = postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is None


def test_delete_session_empty_string_user_id(postgres_db_real: PostgresDb):
    """delete_session with user_id='' should NOT act as wildcard (empty != None)."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.delete_session("s1", user_id="")
    assert result is False

    session = postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is not None


# -- delete_sessions isolation --


def test_delete_sessions_correct_user(postgres_db_real: PostgresDb):
    """delete_sessions with matching user_id only deletes that user's sessions."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))
    postgres_db_real.upsert_session(_make_session("s2", "alice"))
    postgres_db_real.upsert_session(_make_session("s3", "bob"))

    postgres_db_real.delete_sessions(["s1", "s2", "s3"], user_id="alice")

    # Alice's sessions deleted
    assert postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is None
    assert postgres_db_real.get_session(session_id="s2", session_type=SessionType.AGENT) is None

    # Bob's session survives
    bob_session = postgres_db_real.get_session(session_id="s3", session_type=SessionType.AGENT)
    assert bob_session is not None
    assert bob_session.user_id == "bob"


def test_delete_sessions_wrong_user(postgres_db_real: PostgresDb):
    """delete_sessions with wrong user_id deletes nothing."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))
    postgres_db_real.upsert_session(_make_session("s2", "alice"))

    postgres_db_real.delete_sessions(["s1", "s2"], user_id="eve")

    assert postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is not None
    assert postgres_db_real.get_session(session_id="s2", session_type=SessionType.AGENT) is not None


def test_delete_sessions_wildcard(postgres_db_real: PostgresDb):
    """delete_sessions with user_id=None deletes all specified sessions regardless of owner."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))
    postgres_db_real.upsert_session(_make_session("s2", "bob"))

    postgres_db_real.delete_sessions(["s1", "s2"], user_id=None)

    assert postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT) is None
    assert postgres_db_real.get_session(session_id="s2", session_type=SessionType.AGENT) is None


# -- rename_session isolation --


def test_rename_session_correct_user(postgres_db_real: PostgresDb):
    """rename_session with matching user_id succeeds."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Renamed by Alice",
        user_id="alice",
    )
    assert result is not None
    assert result.session_data["session_name"] == "Renamed by Alice"


def test_rename_session_wrong_user(postgres_db_real: PostgresDb):
    """rename_session with wrong user_id is blocked — name unchanged."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Hacked by Bob",
        user_id="bob",
    )
    assert result is None

    # Verify original name unchanged
    session = postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is not None
    assert session.session_data["session_name"] == "Session s1"


def test_rename_session_wildcard(postgres_db_real: PostgresDb):
    """rename_session with user_id=None succeeds (backward compat wildcard)."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Renamed without user",
        user_id=None,
    )
    assert result is not None
    assert result.session_data["session_name"] == "Renamed without user"


def test_rename_session_empty_string_user_id(postgres_db_real: PostgresDb):
    """rename_session with user_id='' should NOT act as wildcard."""
    postgres_db_real.upsert_session(_make_session("s1", "alice"))

    result = postgres_db_real.rename_session(
        session_id="s1",
        session_type=SessionType.AGENT,
        session_name="Hacked by empty",
        user_id="",
    )
    assert result is None

    session = postgres_db_real.get_session(session_id="s1", session_type=SessionType.AGENT)
    assert session is not None
    assert session.session_data["session_name"] == "Session s1"
