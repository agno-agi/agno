from unittest.mock import AsyncMock, Mock, patch

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
async def test_failed_table_creation_can_be_retried(async_mysql_db):
    """A failed CREATE TABLE must not leave the table registered on MetaData."""
    async_mysql_db.create_schema = False
    attempts = {"create": 0}

    async def run_sync(fn, *args, **kwargs):
        attempts["create"] += 1
        if attempts["create"] == 1:
            raise OSError("temporary DDL outage")

    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    async_mysql_db.db_engine.begin = Mock(return_value=begin_ctx)

    session = Mock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=Mock(scalar=Mock(return_value=1)))
    begin_ctx_sess = Mock(__aenter__=AsyncMock(return_value=session), __aexit__=AsyncMock(return_value=None))
    session.begin = Mock(return_value=begin_ctx_sess)
    async_mysql_db.async_session_factory = Mock(return_value=session)

    with (
        patch.object(AsyncMySQLDb, "table_exists", AsyncMock(return_value=False)),
        patch("agno.db.mysql.async_mysql.ais_table_available", AsyncMock(return_value=False)),
        patch.object(AsyncMySQLDb, "upsert_schema_version", AsyncMock()),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            await async_mysql_db._get_or_create_table("retry_table", "knowledge", True)

        table = await async_mysql_db._get_or_create_table("retry_table", "knowledge", True)

    assert table.name == "retry_table"
    assert attempts["create"] == 2
