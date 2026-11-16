"""get_runs / get_run must not answer "no runs" when the run store cannot be read.

A failed read used to come back as [] / None, so a caller could not tell
"nothing stored" from "could not read". A read that fails now raises; a store
that really holds no such run still answers [] / None. Each driver group skips
on its own when its driver is missing, so the SQLite and Redis groups always run.
"""

import inspect

import pytest
from sqlalchemy import JSON, BigInteger, Column, Integer, String, Table
from sqlalchemy.exc import OperationalError

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.db.sqlite import sqlite as sqlite_module
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session import AgentSession

# Nothing listens on port 1, so every connection attempt is refused.
CLOSED_PORT = "127.0.0.1:1"


def _run() -> RunOutput:
    return RunOutput(run_id="r1", agent_id="a1", session_id="s1", content="hi", status=RunStatus.completed)


def _store_run(db) -> None:
    # The SQL runs table references the sessions table, so the session row comes first.
    db.upsert_session(AgentSession(session_id="s1", agent_id="a1"))
    db.upsert_run(_run(), session_id="s1")


async def _astore_run(db) -> None:
    await db.upsert_session(AgentSession(session_id="s1", agent_id="a1"))
    await db.upsert_run(_run(), session_id="s1")


def _fail_checks(monkeypatch, module, name, failing):
    """Make the listed calls (1-based) of the module's table-exists check return False, as a swallowed failure does."""
    real = getattr(module, name)
    calls = []

    def check(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) in failing:
            return False
        return real(*args, **kwargs)

    async def acheck(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) in failing:
            return False
        return await real(*args, **kwargs)

    monkeypatch.setattr(module, name, acheck if inspect.iscoroutinefunction(real) else check)


def _assert_reads_raise(db):
    with pytest.raises(OperationalError):
        db.get_runs(session_id="s1")
    with pytest.raises(OperationalError):
        db.get_runs(deserialize=False)
    with pytest.raises(OperationalError):
        db.get_run("r1")


async def _assert_async_reads_raise(db):
    with pytest.raises(OperationalError):
        await db.get_runs(session_id="s1")
    with pytest.raises(OperationalError):
        await db.get_runs(deserialize=False)
    with pytest.raises(OperationalError):
        await db.get_run("r1")


async def _assert_async_reads_raise_with_runs_table_resolved(db):
    """A running server: the runs table is already in the adapter's cache, so no existence check runs."""
    table = Table(
        db.runs_table_name,
        db.metadata,
        Column("run_id", String, primary_key=True),
        Column("session_id", String),
        Column("run_index", Integer),
        Column("created_at", BigInteger),
        Column("run_type", String),
        Column("run_data", JSON),
        schema=db.db_schema,
    )
    db._store_resolved_table("runs", db.runs_table_name, table)
    assert db._get_cached_table("runs", db.runs_table_name) is table
    await _assert_async_reads_raise(db)


class TestSqlite:
    def test_reads_raise_when_the_database_cannot_be_opened(self, tmp_path):
        # db_url, not db_file: the constructor creates a missing db_file folder.
        _assert_reads_raise(SqliteDb(db_url=f"sqlite:///{tmp_path}/missing/agno.db"))

    def test_missing_runs_table_still_answers_empty(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "agno.db"))
        assert db.get_runs(session_id="s1") == []
        assert db.get_runs(deserialize=False) == ([], 0)
        assert db.get_run("r1") is None

    def test_stored_unknown_and_empty_reads_are_unchanged(self, tmp_path):
        db = SqliteDb(db_file=str(tmp_path / "agno.db"))
        _store_run(db)
        assert [r.run_id for r in db.get_runs(session_id="s1")] == ["r1"]
        assert db.get_run("r1").run_id == "r1"
        assert db.get_run("unknown") is None
        assert db.get_runs(session_id="other") == []


class TestAsyncSqlite:
    @pytest.fixture(autouse=True)
    def _driver(self):
        pytest.importorskip("aiosqlite")

    @pytest.mark.asyncio
    async def test_reads_raise_when_the_database_cannot_be_opened(self, tmp_path):
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        await _assert_async_reads_raise(AsyncSqliteDb(db_url=f"sqlite+aiosqlite:///{tmp_path}/missing/agno.db"))

    @pytest.mark.asyncio
    async def test_missing_runs_table_still_answers_empty(self, tmp_path):
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        db = AsyncSqliteDb(db_file=str(tmp_path / "agno.db"))
        assert await db.get_runs(session_id="s1") == []
        assert await db.get_runs(deserialize=False) == ([], 0)
        assert await db.get_run("r1") is None

    @pytest.mark.asyncio
    async def test_stored_unknown_and_empty_reads_are_unchanged(self, tmp_path):
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        db = AsyncSqliteDb(db_file=str(tmp_path / "agno.db"))
        await _astore_run(db)
        assert [r.run_id for r in await db.get_runs(session_id="s1")] == ["r1"]
        assert (await db.get_run("r1")).run_id == "r1"
        assert await db.get_run("unknown") is None
        assert await db.get_runs(session_id="other") == []


class TestSqliteFirstExistenceCheckFailed:
    """A failed first check (e.g. a stale pooled connection) must not read as "no runs table".

    Each read uses a fresh adapter: the writer has the runs table cached and would skip the check.
    Calls: 1 the first check, 2 the strict recheck, 3 the check when the table is resolved again.
    """

    @pytest.fixture
    def path(self, tmp_path):
        path = str(tmp_path / "agno.db")
        _store_run(SqliteDb(db_file=path))
        return path

    def test_get_runs_returns_the_stored_run(self, path, monkeypatch):
        _fail_checks(monkeypatch, sqlite_module, "is_table_available", {1})
        assert [r.run_id for r in SqliteDb(db_file=path).get_runs(session_id="s1")] == ["r1"]

    def test_get_run_returns_the_stored_run(self, path, monkeypatch):
        _fail_checks(monkeypatch, sqlite_module, "is_table_available", {1})
        run = SqliteDb(db_file=path).get_run("r1")
        assert run is not None and run.run_id == "r1"

    def test_reads_raise_when_the_table_exists_but_cannot_be_resolved(self, path, monkeypatch):
        _fail_checks(monkeypatch, sqlite_module, "is_table_available", {1, 3})
        with pytest.raises(RuntimeError, match="agno_runs"):
            SqliteDb(db_file=path).get_runs(session_id="s1")
        _fail_checks(monkeypatch, sqlite_module, "is_table_available", {1, 3})
        with pytest.raises(RuntimeError, match="agno_runs"):
            SqliteDb(db_file=path).get_run("r1")


class TestAsyncSqliteFirstExistenceCheckFailed:
    """Async twin of TestSqliteFirstExistenceCheckFailed."""

    @pytest.fixture
    async def path(self, tmp_path):
        pytest.importorskip("aiosqlite")
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        path = str(tmp_path / "agno.db")
        await _astore_run(AsyncSqliteDb(db_file=path))
        return path

    @pytest.mark.asyncio
    async def test_get_runs_returns_the_stored_run(self, path, monkeypatch):
        from agno.db.sqlite import async_sqlite
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        _fail_checks(monkeypatch, async_sqlite, "ais_table_available", {1})
        assert [r.run_id for r in await AsyncSqliteDb(db_file=path).get_runs(session_id="s1")] == ["r1"]

    @pytest.mark.asyncio
    async def test_get_run_returns_the_stored_run(self, path, monkeypatch):
        from agno.db.sqlite import async_sqlite
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        _fail_checks(monkeypatch, async_sqlite, "ais_table_available", {1})
        run = await AsyncSqliteDb(db_file=path).get_run("r1")
        assert run is not None and run.run_id == "r1"

    @pytest.mark.asyncio
    async def test_reads_raise_when_the_table_exists_but_cannot_be_resolved(self, path, monkeypatch):
        from agno.db.sqlite import async_sqlite
        from agno.db.sqlite.async_sqlite import AsyncSqliteDb

        _fail_checks(monkeypatch, async_sqlite, "ais_table_available", {1, 3})
        with pytest.raises(RuntimeError, match="agno_runs"):
            await AsyncSqliteDb(db_file=path).get_runs(session_id="s1")
        _fail_checks(monkeypatch, async_sqlite, "ais_table_available", {1, 3})
        with pytest.raises(RuntimeError, match="agno_runs"):
            await AsyncSqliteDb(db_file=path).get_run("r1")


class TestServerAdapters:
    """Postgres, MySQL and SingleStore with the server down: a fresh process, and (async) a running server."""

    def test_postgres(self):
        pytest.importorskip("psycopg")
        from agno.db.postgres import PostgresDb

        _assert_reads_raise(PostgresDb(db_url=f"postgresql+psycopg://u:p@{CLOSED_PORT}/agno"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("running", [False, True], ids=["fresh_process", "running_server"])
    async def test_async_postgres(self, running):
        pytest.importorskip("psycopg")
        from agno.db.postgres import AsyncPostgresDb

        db = AsyncPostgresDb(db_url=f"postgresql+psycopg_async://u:p@{CLOSED_PORT}/agno")
        await (_assert_async_reads_raise_with_runs_table_resolved if running else _assert_async_reads_raise)(db)

    def test_mysql(self):
        pytest.importorskip("pymysql")
        from agno.db.mysql import MySQLDb

        _assert_reads_raise(MySQLDb(db_url=f"mysql+pymysql://u:p@{CLOSED_PORT}/agno"))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("running", [False, True], ids=["fresh_process", "running_server"])
    async def test_async_mysql(self, running):
        pytest.importorskip("asyncmy")
        from agno.db.mysql.async_mysql import AsyncMySQLDb

        db = AsyncMySQLDb(db_url=f"mysql+asyncmy://u:p@{CLOSED_PORT}/agno")
        await (_assert_async_reads_raise_with_runs_table_resolved if running else _assert_async_reads_raise)(db)

    def test_singlestore(self):
        pytest.importorskip("pymysql")
        from agno.db.singlestore.singlestore import SingleStoreDb

        _assert_reads_raise(SingleStoreDb(db_url=f"mysql+pymysql://u:p@{CLOSED_PORT}/agno"))


class TestRedis:
    @pytest.fixture
    def db(self):
        fakeredis = pytest.importorskip("fakeredis")
        from agno.db.redis import RedisDb

        db = RedisDb(redis_client=fakeredis.FakeRedis(), db_prefix="agno")
        db.upsert_run(_run(), session_id="s1")
        return db

    @staticmethod
    def _fail(db, monkeypatch, command):
        from redis.exceptions import ConnectionError as RedisConnectionError

        def down(*args, **kwargs):
            raise RedisConnectionError("redis down")

        monkeypatch.setattr(db.redis_client, command, down)
        return RedisConnectionError

    def test_failed_index_read_raises(self, db, monkeypatch):
        error = self._fail(db, monkeypatch, "zrange")
        with pytest.raises(error):
            db.get_runs(session_id="s1")

    def test_failed_record_read_raises(self, db, monkeypatch):
        error = self._fail(db, monkeypatch, "get")
        with pytest.raises(error):
            db.get_run("r1")
        with pytest.raises(error):
            db.get_runs(session_id="s1")

    def test_failed_key_scan_raises(self, db, monkeypatch):
        error = self._fail(db, monkeypatch, "scan_iter")
        with pytest.raises(error):
            db.get_runs()

    def test_undecodable_record_raises(self, db):
        db.redis_client.set("agno:runs:r1", b"\xff not json")
        with pytest.raises(ValueError):
            db.get_run("r1")
        with pytest.raises(ValueError):
            db.get_runs(session_id="s1")
        with pytest.raises(ValueError):
            db.get_runs()

    def test_index_entry_without_a_record_is_skipped(self, db):
        db.redis_client.zadd(db._runs_by_session_index_key("s1"), {"gone": 5})
        assert [r.run_id for r in db.get_runs(session_id="s1")] == ["r1"]

    def test_stored_unknown_and_empty_reads_are_unchanged(self, db):
        assert [r.run_id for r in db.get_runs()] == ["r1"]
        assert db.get_run("r1").run_id == "r1"
        assert db.get_run("unknown") is None
        assert db.get_runs(session_id="other") == []

    def test_other_reads_keep_answering_none_on_a_failed_read(self, db, monkeypatch):
        self._fail(db, monkeypatch, "get")
        assert db.get_session("s1", session_type=SessionType.AGENT) is None
