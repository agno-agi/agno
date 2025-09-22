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
# pytest libs/agno/tests/integration/db/surrealdb/test_surrealdb_memory.py
# ```

import pytest
from surrealdb import RecordID

from agno.db.base import SessionType
from agno.db.surrealdb import SurrealDb
from agno.debug import enable_debug_mode
from agno.session.agent import AgentSession

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


def test_crud_memory(db: SurrealDb):
    session = AgentSession(session_id="123", agent_id="1")

    # upsert
    db.upsert_session(session)

    # list
    sessions = db.get_sessions(SessionType.AGENT)
    assert isinstance(sessions, list)
    assert len(sessions) == 1
    assert sessions[0].session_id == "123"

    # list, unserialized
    sessions = db.get_sessions(SessionType.AGENT, deserialize=False)
    assert isinstance(sessions, tuple) and len(sessions[0]) == 1 and sessions[1] == 1

    # find one
    session_got = db.get_session("123", SessionType.AGENT)
    assert isinstance(session_got, AgentSession) and session_got.session_id == "123"

    # find one, wrong type
    wrong = db.get_session("123", SessionType.TEAM)
    assert wrong is None

    # rename
    renamed = db.rename_session("123", SessionType.AGENT, "new name", False)
    assert (
        isinstance(renamed, dict)
        and renamed.get("agent") == RecordID("agent", "1")
        and renamed.get("session_name") == "new name"
    )

    # delete
    deleted = db.delete_session("123")
    assert deleted

    # list, emtpy
    sessions = db.get_sessions(SessionType.AGENT, deserialize=False)
    assert isinstance(sessions, tuple) and len(sessions[0]) == 0 and sessions[1] == 0
