from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import Column, Integer, MetaData, Table
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.mysql.async_mysql import AsyncMySQLDb
from agno.db.mysql.mysql import MySQLDb


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
async def test_get_runs_strict_distinguishes_missing_table_and_read_failure(async_mysql_db):
    async_mysql_db._get_table = AsyncMock(return_value=None)
    assert await async_mysql_db.get_runs(deserialize=False) == ([], 0)
    with pytest.raises(RuntimeError, match="runs table is unavailable"):
        await async_mysql_db.get_runs(deserialize=False, raise_on_error=True)

    async_mysql_db._get_table = AsyncMock(side_effect=OSError("server closed"))
    assert await async_mysql_db.get_runs(deserialize=False) == ([], 0)
    with pytest.raises(OSError, match="server closed"):
        await async_mysql_db.get_runs(deserialize=False, raise_on_error=True)


def test_sync_mysql_get_runs_strict_rejects_missing_table():
    db = object.__new__(MySQLDb)
    db._get_table = Mock(return_value=None)
    assert db.get_runs(deserialize=False) == ([], 0)
    with pytest.raises(RuntimeError, match="runs table is unavailable"):
        db.get_runs(deserialize=False, raise_on_error=True)


@pytest.mark.asyncio
async def test_async_mysql_get_runs_strict_accepts_verified_empty_table(async_mysql_db):
    table = Table("runs", MetaData(), Column("run_index", Integer), Column("created_at", Integer))
    async_mysql_db._get_table = AsyncMock(return_value=table)
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.scalar = AsyncMock(return_value=0)
    session.execute = AsyncMock(return_value=Mock(fetchall=Mock(return_value=[])))
    async_mysql_db.async_session_factory = Mock(return_value=session)

    assert await async_mysql_db.get_runs(deserialize=False, raise_on_error=True) == ([], 0)


def test_sync_mysql_get_runs_strict_accepts_verified_empty_table():
    db = object.__new__(MySQLDb)
    db._get_table = Mock(
        return_value=Table("runs", MetaData(), Column("run_index", Integer), Column("created_at", Integer))
    )
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.execute.side_effect = [Mock(scalar=Mock(return_value=0)), Mock(fetchall=Mock(return_value=[]))]
    db.Session = Mock(return_value=session)

    assert db.get_runs(deserialize=False, raise_on_error=True) == ([], 0)
