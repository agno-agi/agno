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


# -- delete_run / delete_runs: a failed delete is not a missing run --
#
# The sync twin in agno/db/mysql/mysql.py re-raises here, and so do 13 of the 17 db
# backends. AsyncSqliteDb and AsyncMongoDb re-raise too, so this is not an async
# convention - it is this file diverging from its own sync twin.


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
