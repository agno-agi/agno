import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.mysql.async_mysql import AsyncMySQLDb


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
    return engine


@pytest.fixture
def async_mysql_db(mock_async_engine):
    """Create an AsyncMySQLDb instance with mock engine"""
    return AsyncMySQLDb(
        db_engine=mock_async_engine,
        db_schema="test_schema",
        session_table="test_sessions",
    )


def _session_raising(error: Exception) -> Mock:
    """An async session factory whose execute() fails the way a live backend does."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin = Mock(return_value=session)
    session.execute = AsyncMock(side_effect=error)
    return Mock(return_value=session)


@pytest.mark.asyncio
async def test_delete_run_raises_on_a_backend_failure(async_mysql_db):
    """False means the run was not found. A dropped connection must not say that."""
    async_mysql_db._get_table = AsyncMock(return_value=Mock())
    async_mysql_db.async_session_factory = _session_raising(OSError("server closed the connection"))

    with pytest.raises(OSError, match="server closed"):
        await async_mysql_db.delete_run("run-1")


@pytest.mark.asyncio
async def test_delete_run_still_returns_false_when_there_is_no_such_run(async_mysql_db):
    """The meaning of False, pinned so it is not lost to the fix above."""
    async_mysql_db._get_table = AsyncMock(return_value=None)

    assert await async_mysql_db.delete_run("run-1") is False


@pytest.mark.asyncio
async def test_delete_runs_raises_on_a_backend_failure(async_mysql_db):
    async_mysql_db._get_table = AsyncMock(return_value=Mock())
    async_mysql_db.async_session_factory = _session_raising(OSError("server closed the connection"))

    with pytest.raises(OSError, match="server closed"):
        await async_mysql_db.delete_runs(["run-1", "run-2"])


@pytest.mark.asyncio
async def test_failed_table_creation_can_be_retried_async_mysql(async_mysql_db):
    """A failed CREATE TABLE on AsyncMySQLDb must unregister the table from MetaData."""
    from unittest.mock import patch

    async_mysql_db.create_schema = False
    attempts = {"create": 0}

    async def run_sync(fn, *args, **kwargs):
        attempts["create"] += 1
        if attempts["create"] == 1:
            raise OSError("temporary DDL outage")

    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    async_mysql_db.db_engine.begin = Mock(return_value=begin_ctx)

    with (
        patch.object(AsyncMySQLDb, "table_exists", AsyncMock(return_value=False)),
        patch.object(AsyncMySQLDb, "upsert_schema_version", AsyncMock()),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            await async_mysql_db._create_table("retry_table", "knowledge")

        table = await async_mysql_db._create_table("retry_table", "knowledge")

    assert table.name == "retry_table"
    assert attempts["create"] == 2


def test_failed_table_creation_can_be_retried_mysql():
    """A failed CREATE TABLE on MySQLDb must unregister the table from MetaData."""
    from unittest.mock import Mock, patch

    from sqlalchemy import Table
    from sqlalchemy.engine import Engine

    from agno.db.mysql.mysql import MySQLDb

    mock_engine = Mock(spec=Engine)
    mock_engine.url = "fake:///url"
    mysql_db = MySQLDb(db_engine=mock_engine, db_schema="test_schema", session_table="test_sessions")

    attempts = {"create": 0}

    def failing_create(table, *args, **kwargs):
        if table.name == "retry_table":
            attempts["create"] += 1
            if attempts["create"] == 1:
                raise OSError("temporary DDL outage")

    with (
        patch.object(MySQLDb, "table_exists", return_value=False),
        patch.object(MySQLDb, "upsert_schema_version", Mock()),
        patch.object(Table, "create", failing_create),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            mysql_db._create_table("retry_table", "knowledge")

        table = mysql_db._create_table("retry_table", "knowledge")

    assert table.name == "retry_table"
    assert attempts["create"] == 2


@pytest.mark.asyncio
async def test_cancelled_table_creation_can_be_retried_async_mysql(async_mysql_db):
    """A cancelled CREATE TABLE on AsyncMySQLDb must unregister the table from MetaData."""
    async_mysql_db.create_schema = False
    started = asyncio.Event()
    attempts = 0

    async def table_exists(table_name):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            started.set()
            await asyncio.Event().wait()
        return False

    conn = Mock(run_sync=AsyncMock())
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    async_mysql_db.db_engine.begin = Mock(return_value=begin_ctx)
    async_mysql_db.table_exists = table_exists
    async_mysql_db.upsert_schema_version = AsyncMock()

    task = asyncio.create_task(async_mysql_db._create_table("retry_table", "knowledge"))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    table = await async_mysql_db._create_table("retry_table", "knowledge")

    assert table.name == "retry_table"
    assert attempts == 2
