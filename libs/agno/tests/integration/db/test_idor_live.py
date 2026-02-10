"""
Live IDOR (Insecure Direct Object Reference) tests for session isolation.

Tests that user_id filtering actually works at the DB level against real backends.
Run with: cd libs/agno && uv run --no-sync pytest tests/integration/db/test_idor_live.py -v

Individual backends:
  pytest tests/integration/db/test_idor_live.py::TestInMemoryIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestPostgresIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestPostgresAsyncIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestSqliteIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestSqliteAsyncIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestMongoIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestMongoAsyncIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestMySQLIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestRedisIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestJsonIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestSurrealIDOR -v
  pytest tests/integration/db/test_idor_live.py::TestDynamoIDOR -v
"""

import shutil
import time
from typing import Optional
from uuid import uuid4

import pytest

from agno.db.base import SessionType
from agno.session import AgentSession


def _make_agent_session(
    session_id: str,
    user_id: Optional[str] = None,
    agent_id: str = "test-agent",
    session_name: str = "test-session",
) -> AgentSession:
    return AgentSession(
        session_id=session_id,
        agent_id=agent_id,
        user_id=user_id,
        created_at=int(time.time()),
        session_data={"session_name": session_name},
    )


# ─────────────────────────────────────────────
# InMemory backend
# ─────────────────────────────────────────────


class TestInMemoryIDOR:
    @pytest.fixture(autouse=True)
    def setup(self):
        from agno.db.in_memory.in_memory_db import InMemoryDb

        self.db = InMemoryDb()
        self.alice_sid = f"mem-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"mem-bob-{uuid4().hex[:8]}"

        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Chat"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Chat"))

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None
        assert result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        assert self.db.delete_session(self.alice_sid, user_id="alice") is True
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is None

    def test_delete_sessions_bulk_isolation(self):
        self.db.delete_sessions([self.alice_sid, self.bob_sid], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None
        assert self.db.get_session(self.bob_sid, SessionType.AGENT, user_id="bob") is None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice Chat"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "New Name", user_id="alice")
        assert result is not None
        assert result.session_data.get("session_name") == "New Name"

    def test_get_sessions_filters_by_user(self):
        alice_sessions = self.db.get_sessions(SessionType.AGENT, user_id="alice")
        assert len(alice_sessions) == 1
        assert alice_sessions[0].session_id == self.alice_sid


# ─────────────────────────────────────────────
# Postgres sync backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def pg_engine():
    try:
        from sqlalchemy.engine import create_engine
        from sqlalchemy.sql import text

        engine = create_engine("postgresql+psycopg://ai:ai@localhost:5532/ai")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.commit()
        yield engine
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS idor_test CASCADE"))
            conn.commit()
        engine.dispose()
    except Exception:
        pytest.skip("Postgres not available at localhost:5532")


@pytest.fixture
def pg_db(pg_engine):
    from agno.db.postgres.postgres import PostgresDb

    db = PostgresDb(db_engine=pg_engine, db_schema="idor_test", session_table="idor_sessions")
    yield db


class TestPostgresIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, pg_db):
        self.db = pg_db
        self.alice_sid = f"pg-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"pg-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice PG Chat"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob PG Chat"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"pg-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True
        assert self.db.get_session(extra, SessionType.AGENT, user_id="alice") is None

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"pg-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None
        assert self.db.get_session(extra_bob, SessionType.AGENT, user_id="bob") is None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice PG Chat"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None and result.session_data.get("session_name") == "Renamed"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# Postgres async backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def pg_async_engine():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine("postgresql+psycopg://ai:ai@localhost:5532/ai")
        yield engine
    except Exception:
        pytest.skip("Async Postgres not available")


@pytest.fixture
def pg_async_db(pg_async_engine):
    from agno.db.postgres.async_postgres import AsyncPostgresDb

    db = AsyncPostgresDb(db_engine=pg_async_engine, db_schema="idor_test_async", session_table="idor_async_sessions")
    yield db


class TestPostgresAsyncIDOR:
    @pytest.fixture(autouse=True)
    async def setup(self, pg_async_db):
        self.db = pg_async_db
        self.alice_sid = f"pga-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"pga-bob-{uuid4().hex[:8]}"
        await self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Async"))
        await self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Async"))
        yield
        await self.db.delete_session(self.alice_sid)
        await self.db.delete_session(self.bob_sid)

    @pytest.mark.asyncio
    async def test_read_isolation_blocks_cross_user(self):
        assert await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    @pytest.mark.asyncio
    async def test_read_own_session(self):
        result = await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    @pytest.mark.asyncio
    async def test_delete_isolation_blocks_cross_user(self):
        assert await self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    @pytest.mark.asyncio
    async def test_rename_isolation_blocks_cross_user(self):
        assert await self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None

    @pytest.mark.asyncio
    async def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert await self.db.upsert_session(hijack) is None
        original = await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"


# ─────────────────────────────────────────────
# SQLite sync backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def sqlite_engine():
    try:
        from sqlalchemy.engine import create_engine

        engine = create_engine("sqlite:///idor_test.db")
        yield engine
        engine.dispose()
        import os

        try:
            os.unlink("idor_test.db")
        except FileNotFoundError:
            pass
    except Exception:
        pytest.skip("SQLite not available")


@pytest.fixture
def sqlite_db(sqlite_engine):
    from agno.db.sqlite.sqlite import SqliteDb

    db = SqliteDb(db_engine=sqlite_engine, session_table="idor_sessions")
    yield db


class TestSqliteIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, sqlite_db):
        self.db = sqlite_db
        self.alice_sid = f"sq-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"sq-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice SQLite"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob SQLite"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"sq-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"sq-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice SQLite"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None and result.session_data.get("session_name") == "Renamed"

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# SQLite async backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def sqlite_async_engine():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine("sqlite+aiosqlite:///idor_test_async.db")
        yield engine
    except Exception:
        pytest.skip("Async SQLite not available (aiosqlite missing)")


@pytest.fixture
def sqlite_async_db(sqlite_async_engine):
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    db = AsyncSqliteDb(db_engine=sqlite_async_engine, session_table="idor_async_sessions")
    yield db


class TestSqliteAsyncIDOR:
    @pytest.fixture(autouse=True)
    async def setup(self, sqlite_async_db):
        self.db = sqlite_async_db
        self.alice_sid = f"sqa-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"sqa-bob-{uuid4().hex[:8]}"
        await self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Async"))
        await self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Async"))
        yield
        await self.db.delete_session(self.alice_sid)
        await self.db.delete_session(self.bob_sid)

    @pytest.mark.asyncio
    async def test_read_isolation_blocks_cross_user(self):
        assert await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    @pytest.mark.asyncio
    async def test_read_own_session(self):
        result = await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None

    @pytest.mark.asyncio
    async def test_delete_isolation_blocks_cross_user(self):
        assert await self.db.delete_session(self.alice_sid, user_id="bob") is False

    @pytest.mark.asyncio
    async def test_rename_isolation_blocks_cross_user(self):
        assert await self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None

    @pytest.mark.asyncio
    async def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert await self.db.upsert_session(hijack) is None
        original = await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"


# ─────────────────────────────────────────────
# MongoDB sync backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def mongo_client():
    try:
        from pymongo import MongoClient

        client = MongoClient("mongodb://mongoadmin:secret@localhost:27017", serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        yield client
        client.drop_database("idor_test")
        client.close()
    except Exception:
        pytest.skip("MongoDB not available at localhost:27017")


@pytest.fixture
def mongo_db(mongo_client):
    from agno.db.mongo.mongo import MongoDb

    db = MongoDb(db_client=mongo_client, db_name="idor_test", session_collection="idor_sessions")
    yield db


class TestMongoIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, mongo_db):
        self.db = mongo_db
        self.alice_sid = f"mg-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"mg-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Mongo"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Mongo"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"mg-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"mg-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice Mongo"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None and result.session_data.get("session_name") == "Renamed"

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# MongoDB async backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def mongo_async_client():
    try:
        from pymongo import AsyncMongoClient  # type: ignore

        client = AsyncMongoClient("mongodb://mongoadmin:secret@localhost:27017", serverSelectionTimeoutMS=3000)
        yield client
    except Exception:
        pytest.skip("Async MongoDB not available (pymongo >= 4.9 needed)")


@pytest.fixture
def mongo_async_db(mongo_async_client):
    from agno.db.mongo.async_mongo import AsyncMongoDb

    db = AsyncMongoDb(db_client=mongo_async_client, db_name="idor_test_async", session_collection="idor_async_sessions")
    yield db


class TestMongoAsyncIDOR:
    @pytest.fixture(autouse=True)
    async def setup(self, mongo_async_db):
        self.db = mongo_async_db
        self.alice_sid = f"mga-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"mga-bob-{uuid4().hex[:8]}"
        await self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Async"))
        await self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Async"))
        yield
        await self.db.delete_session(self.alice_sid)
        await self.db.delete_session(self.bob_sid)

    @pytest.mark.asyncio
    async def test_read_isolation_blocks_cross_user(self):
        assert await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    @pytest.mark.asyncio
    async def test_read_own_session(self):
        result = await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None

    @pytest.mark.asyncio
    async def test_delete_isolation_blocks_cross_user(self):
        assert await self.db.delete_session(self.alice_sid, user_id="bob") is False

    @pytest.mark.asyncio
    async def test_rename_isolation_blocks_cross_user(self):
        assert await self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None

    @pytest.mark.asyncio
    async def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert await self.db.upsert_session(hijack) is None
        original = await self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"


# ─────────────────────────────────────────────
# MySQL sync backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def mysql_engine():
    try:
        from sqlalchemy.engine import create_engine
        from sqlalchemy.sql import text

        engine = create_engine("mysql+pymysql://ai:ai@localhost:3306/ai")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.commit()
        yield engine
        engine.dispose()
    except Exception:
        pytest.skip("MySQL not available at localhost:3306")


@pytest.fixture
def mysql_db(mysql_engine):
    from agno.db.mysql.mysql import MySQLDb

    db = MySQLDb(db_engine=mysql_engine, session_table="idor_sessions")
    yield db


class TestMySQLIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, mysql_db):
        self.db = mysql_db
        self.alice_sid = f"my-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"my-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice MySQL"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob MySQL"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"my-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"my-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice MySQL"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None and result.session_data.get("session_name") == "Renamed"

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# Redis backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def redis_client():
    try:
        from redis import Redis

        client = Redis(host="localhost", port=6379, decode_responses=True)
        client.ping()
        yield client
        # Clean up IDOR test keys
        for key in client.scan_iter("idor_test:*"):
            client.delete(key)
        client.close()
    except Exception:
        pytest.skip("Redis not available at localhost:6379")


@pytest.fixture
def redis_db(redis_client):
    from agno.db.redis.redis import RedisDb

    db = RedisDb(redis_client=redis_client, db_prefix="idor_test", session_table="idor_sessions")
    yield db


class TestRedisIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, redis_db):
        self.db = redis_db
        self.alice_sid = f"rd-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"rd-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Redis"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Redis"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"rd-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"rd-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice Redis"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None and result.session_data.get("session_name") == "Renamed"

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# JSON file backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def json_db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("idor_json_test")
    yield str(path)
    shutil.rmtree(str(path), ignore_errors=True)


@pytest.fixture
def json_db(json_db_path):
    from agno.db.json.json_db import JsonDb

    db = JsonDb(db_path=json_db_path, session_table="idor_sessions")
    yield db


class TestJsonIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, json_db):
        self.db = json_db
        self.alice_sid = f"js-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"js-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice JSON"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob JSON"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"js-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"js-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original.session_data.get("session_name") == "Alice JSON"

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None and result.session_data.get("session_name") == "Renamed"

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# SurrealDB backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def surreal_client():
    try:
        from agno.db.surrealdb.utils import build_client

        client = build_client(
            url="ws://localhost:8000",
            creds={"username": "root", "password": "root"},
            ns="idor_test",
            db="idor_test",
        )
        yield client
    except Exception:
        pytest.skip("SurrealDB not available at localhost:8000")


@pytest.fixture
def surreal_db(surreal_client):
    from agno.db.surrealdb.surrealdb import SurrealDb

    db = SurrealDb(
        client=surreal_client,
        db_url="ws://localhost:8000",
        db_creds={"username": "root", "password": "root"},
        db_ns="idor_test",
        db_db="idor_test",
        session_table="idor_sessions",
    )
    yield db


class TestSurrealIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, surreal_db):
        self.db = surreal_db
        self.alice_sid = f"sr-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"sr-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Surreal"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Surreal"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"sr-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"sr-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"


# ─────────────────────────────────────────────
# DynamoDB backend
# ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def dynamo_client():
    try:
        import boto3

        client = boto3.client(
            "dynamodb",
            endpoint_url="http://localhost:8010",
            region_name="us-east-1",
            aws_access_key_id="test",
            aws_secret_access_key="test",
        )
        client.list_tables()
        yield client
        try:
            client.delete_table(TableName="idor_sessions")
        except Exception:
            pass
    except Exception:
        pytest.skip("DynamoDB Local not available at localhost:8010")


@pytest.fixture
def dynamo_db(dynamo_client):
    from agno.db.dynamo.dynamo import DynamoDb

    db = DynamoDb(
        db_client=dynamo_client,
        session_table="idor_sessions",
    )
    yield db


class TestDynamoIDOR:
    @pytest.fixture(autouse=True)
    def setup(self, dynamo_db):
        self.db = dynamo_db
        self.alice_sid = f"dy-alice-{uuid4().hex[:8]}"
        self.bob_sid = f"dy-bob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(self.alice_sid, user_id="alice", session_name="Alice Dynamo"))
        self.db.upsert_session(_make_agent_session(self.bob_sid, user_id="bob", session_name="Bob Dynamo"))
        yield
        self.db.delete_session(self.alice_sid)
        self.db.delete_session(self.bob_sid)

    def test_read_own_session(self):
        result = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert result is not None and result.session_id == self.alice_sid

    def test_read_isolation_blocks_cross_user(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="bob") is None

    def test_read_without_user_id_returns_any(self):
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id=None) is not None

    def test_delete_isolation_blocks_cross_user(self):
        assert self.db.delete_session(self.alice_sid, user_id="bob") is False
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_delete_own_session_works(self):
        extra = f"dy-extra-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra, user_id="alice", session_name="Extra"))
        assert self.db.delete_session(extra, user_id="alice") is True

    def test_delete_sessions_bulk_isolation(self):
        extra_bob = f"dy-extrabob-{uuid4().hex[:8]}"
        self.db.upsert_session(_make_agent_session(extra_bob, user_id="bob", session_name="Bob Extra"))
        self.db.delete_sessions([self.alice_sid, extra_bob], user_id="bob")
        assert self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice") is not None

    def test_rename_isolation_blocks_cross_user(self):
        assert self.db.rename_session(self.alice_sid, SessionType.AGENT, "Hacked", user_id="bob") is None

    def test_upsert_hijack_blocked(self):
        hijack = _make_agent_session(self.alice_sid, user_id="bob", session_name="Hijacked")
        assert self.db.upsert_session(hijack) is None
        original = self.db.get_session(self.alice_sid, SessionType.AGENT, user_id="alice")
        assert original is not None and original.user_id == "alice"

    def test_rename_own_session_works(self):
        result = self.db.rename_session(self.alice_sid, SessionType.AGENT, "Renamed", user_id="alice")
        assert result is not None

    def test_get_sessions_filters_by_user(self):
        for s in self.db.get_sessions(SessionType.AGENT, user_id="alice"):
            assert s.user_id == "alice"
