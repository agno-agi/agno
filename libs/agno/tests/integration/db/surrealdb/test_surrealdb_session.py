# Run SurrealDB in a container before running this script
#
# ```
# docker run --rm --pull always -p 8000:8000 surrealdb/surrealdb:latest start --user root --pass root
# ```
#
# or with
#
# ```
# surreal start -u root -p root
# ```
#
# Then, run this test like this:
#
# ```
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_session.py
# ```

import time
from datetime import datetime

import pytest
from surrealdb import RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import SurrealDb
from agno.debug import enable_debug_mode
from agno.session.agent import AgentSession
from agno.session.team import TeamSession

enable_debug_mode()

# SurrealDB connection parameters
SURREALDB_URL = "ws://localhost:8000"
SURREALDB_USER = "root"
SURREALDB_PASSWORD = "root"
SURREALDB_NAMESPACE = "test"
SURREALDB_DATABASE = "test"


@pytest.fixture
def db() -> SurrealDb:
    """Create a SurrealDB memory database for testing."""
    creds = {"username": SURREALDB_USER, "password": SURREALDB_PASSWORD}
    db = SurrealDb(None, SURREALDB_URL, creds, SURREALDB_NAMESPACE, SURREALDB_DATABASE)
    return db


# TODO: add tests for get_sessions using filters and sorting
def test_crud_sessions(db: SurrealDb):
    db.delete_sessions(["1", "2"])
    _, count = db.get_sessions(SessionType.AGENT, deserialize=False)
    assert count == 0

    now = int(datetime.now().timestamp())
    session = AgentSession(session_id="1", agent_id="1", created_at=now)
    session2 = AgentSession(session_id="2", agent_id="2")

    # upsert
    db.upsert_session(session)

    # list
    sessions = db.get_sessions(SessionType.AGENT)
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    assert sessions[0].session_id == "1"
    assert isinstance(sessions[0], AgentSession)
    assert sessions[0].agent_id == "1"

    # list, unserialized
    sessions = db.get_sessions(SessionType.AGENT, deserialize=False)
    assert isinstance(sessions, tuple) and len(sessions[0]) == 1 and sessions[1] == 1

    # find one
    session_got = db.get_session("1", SessionType.AGENT)
    assert isinstance(session_got, AgentSession) and session_got.session_id == "1"

    # get_session uses session_type for deserialization only, not filtering
    cross = db.get_session("1", SessionType.TEAM)
    assert isinstance(cross, TeamSession) and cross.session_id == "1"

    # rename
    renamed = db.rename_session("1", SessionType.AGENT, "new name", deserialize=False)
    assert (
        isinstance(renamed, dict)
        and renamed.get("agent") == RecordID(db.table_names["agents"], "1")
        and renamed.get("session_name") == "new name"
    )

    # delete
    deleted = db.delete_session("1")
    assert deleted

    # list, emtpy
    sessions = db.get_sessions(SessionType.AGENT, deserialize=False)
    assert isinstance(sessions, tuple) and len(sessions[0]) == 0 and sessions[1] == 0

    # upsert
    _ = db.upsert_sessions([session, session2])
    _, count = db.get_sessions(SessionType.AGENT, deserialize=False)
    assert count == 2


def test_session_created_at_preserved_on_update(db: SurrealDb):
    """Test that session created_at is preserved when updating."""
    db.delete_session("3")

    now = int(datetime.now().timestamp())
    session = AgentSession(session_id="3", agent_id="3", created_at=now)
    db.upsert_session(session)

    created_session = db.get_session("3", SessionType.AGENT, deserialize=False)
    assert created_session is not None
    original_created_at = created_session.get("created_at")
    original_updated_at = created_session.get("updated_at")

    time.sleep(1.1)

    session.session_name = "Updated Name"
    db.upsert_session(session)

    updated_session = db.get_session("3", SessionType.AGENT, deserialize=False)
    assert updated_session is not None
    new_created_at = updated_session.get("created_at")
    new_updated_at = updated_session.get("updated_at")

    db.delete_session("3")

    # created_at should not change on update
    assert original_created_at == new_created_at
    # updated_at should change on update
    assert original_updated_at != new_updated_at


# ── session_type=None integration tests ──────────────────────────────────────


def test_get_sessions_without_type_returns_all(db: SurrealDb):
    """get_sessions(session_type=None) returns agent and team sessions together."""
    db.delete_sessions(["none-type-1", "none-type-2"])

    now = int(datetime.now().timestamp())
    agent = AgentSession(session_id="none-type-1", agent_id="a1", created_at=now)
    team = TeamSession(session_id="none-type-2", team_id="t1", created_at=now)

    db.upsert_session(agent)
    db.upsert_session(team)

    # session_type=None should return both
    sessions_raw, total_count = db.get_sessions(session_type=None, deserialize=False)
    assert total_count >= 2
    session_ids = {s["session_id"] for s in sessions_raw}
    assert "none-type-1" in session_ids
    assert "none-type-2" in session_ids

    # Deserialized path should auto-detect correct types
    sessions = db.get_sessions(session_type=None)
    assert len(sessions) >= 2
    types = {type(s) for s in sessions}
    assert AgentSession in types
    assert TeamSession in types

    db.delete_sessions(["none-type-1", "none-type-2"])


def test_get_session_without_type_auto_detects(db: SurrealDb):
    """get_session(session_type=None) auto-detects the correct session type for deserialization."""
    db.delete_sessions(["auto-1", "auto-2"])

    now = int(datetime.now().timestamp())
    agent = AgentSession(session_id="auto-1", agent_id="a1", created_at=now)
    team = TeamSession(session_id="auto-2", team_id="t1", created_at=now)

    db.upsert_session(agent)
    db.upsert_session(team)

    result = db.get_session("auto-1", session_type=None)
    assert result is not None
    assert isinstance(result, AgentSession)
    assert result.session_id == "auto-1"

    result = db.get_session("auto-2", session_type=None)
    assert result is not None
    assert isinstance(result, TeamSession)
    assert result.session_id == "auto-2"

    db.delete_sessions(["auto-1", "auto-2"])


def test_rename_session_without_type(db: SurrealDb):
    """rename_session(session_type=None) works without specifying session type."""
    db.delete_session("rename-none-1")

    now = int(datetime.now().timestamp())
    agent = AgentSession(session_id="rename-none-1", agent_id="a1", created_at=now)
    db.upsert_session(agent)

    result = db.rename_session("rename-none-1", session_type=None, session_name="Renamed")
    assert result is not None
    assert isinstance(result, AgentSession)

    db.delete_session("rename-none-1")
