"""SurrealDb storage against a real in-process engine, so SDK behavior changes cannot hide behind mocks."""

from uuid import uuid4

import pytest

from agno.db.base import SessionType
from agno.db.schemas.memory import UserMemory
from agno.db.surrealdb import SurrealDb
from agno.session import AgentSession

surrealdb = pytest.importorskip("surrealdb")


@pytest.fixture
def db() -> SurrealDb:
    client = surrealdb.Surreal("mem://")
    database = uuid4().hex
    client.use("test", database)
    return SurrealDb(client, "mem://", {}, "test", database)


def _session(session_id: str = "s1") -> AgentSession:
    return AgentSession(session_id=session_id, agent_id="a1", user_id="u1", created_at=1700000000)


def test_session_round_trip_and_delete(db: SurrealDb):
    db.upsert_session(_session())

    stored = db.get_session("s1", SessionType.AGENT)
    assert stored is not None
    assert stored.session_id == "s1"

    assert db.delete_session("s1") is True
    assert db.get_session("s1", SessionType.AGENT) is None


def test_memory_round_trip_and_delete(db: SurrealDb):
    stored = db.upsert_user_memory(UserMemory(memory="likes tea", user_id="u1", memory_id="m1"))
    assert stored is not None

    fetched = db.get_user_memory("m1")
    assert fetched is not None
    assert fetched.memory == "likes tea"

    db.delete_user_memory("m1")
    assert db.get_user_memory("m1") is None


def test_clear_memories_removes_every_row(db: SurrealDb):
    db.upsert_user_memory(UserMemory(memory="likes tea", user_id="u1", memory_id="m1"))

    db.clear_memories()

    assert db.get_user_memories() == []


def test_schema_version_round_trip(db: SurrealDb):
    db.upsert_schema_version("agno_sessions", "3.1.0")

    assert db.get_latest_schema_version("agno_sessions") == "3.1.0"
