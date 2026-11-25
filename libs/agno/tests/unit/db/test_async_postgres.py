import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from agno.db.postgres.async_postgres import AsyncPostgresDb


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    engine = Mock(spec=AsyncEngine)
    engine.url = "fake:///url"
    return engine


@pytest.fixture
def async_postgres_db(mock_async_engine):
    """Create an AsyncPostgresDb instance with mock engine"""
    return AsyncPostgresDb(
        db_engine=mock_async_engine,
        db_schema="test_schema",
        session_table="test_sessions",
    )


@pytest.mark.asyncio
@patch("agno.db.postgres.async_postgres.ais_table_available", new_callable=AsyncMock)
async def test_get_or_create_table_returns_none_when_not_available(mock_is_available, async_postgres_db):
    """Test that _get_or_create_table returns None when table doesn't exist and create_table_if_not_found=False"""
    mock_is_available.return_value = False

    mock_session = AsyncMock()
    async_postgres_db.async_session_factory = Mock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin = Mock(return_value=mock_session)

    result = await async_postgres_db._get_or_create_table(
        table_name="test_table", table_type="approvals", create_table_if_not_found=False
    )

    assert result is None


@pytest.mark.asyncio
@patch("agno.db.postgres.async_postgres.ais_table_available", new_callable=AsyncMock)
async def test_get_or_create_table_creates_when_not_available_and_create_flag_set(mock_is_available, async_postgres_db):
    """Test that _get_or_create_table creates the table when not available and create_table_if_not_found=True"""
    mock_is_available.return_value = False

    mock_session = AsyncMock()
    async_postgres_db.async_session_factory = Mock(return_value=mock_session)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.begin = Mock(return_value=mock_session)

    mock_table = Mock()
    async_postgres_db._create_table = AsyncMock(return_value=mock_table)

    result = await async_postgres_db._get_or_create_table(
        table_name="test_table", table_type="sessions", create_table_if_not_found=True
    )

    assert result == mock_table
    async_postgres_db._create_table.assert_called_once_with(table_name="test_table", table_type="sessions")


@pytest.mark.asyncio
async def test_failed_table_creation_can_be_retried(async_postgres_db):
    """A failed CREATE TABLE must not leave the table registered on MetaData."""
    async_postgres_db.create_schema = False
    attempts = {"create": 0}

    async def run_sync(fn, *args, **kwargs):
        attempts["create"] += 1
        if attempts["create"] == 1:
            raise OSError("temporary DDL outage")

    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    async_postgres_db.db_engine.begin = Mock(return_value=begin_ctx)

    # Every index already exists, so only the table DDL goes through run_sync.
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.execute = AsyncMock(return_value=Mock(scalar=Mock(return_value=1)))
    async_postgres_db.async_session_factory = Mock(return_value=session)

    with (
        patch.object(AsyncPostgresDb, "table_exists", AsyncMock(return_value=False)),
        patch.object(AsyncPostgresDb, "upsert_schema_version", AsyncMock()),
    ):
        with pytest.raises(OSError, match="temporary DDL outage"):
            await async_postgres_db._create_table("retry_table", "knowledge")

        table = await async_postgres_db._create_table("retry_table", "knowledge")

    assert table.name == "retry_table"
    assert attempts["create"] == 2


@pytest.mark.asyncio
async def test_get_schedules_default_swallows_error(async_postgres_db, monkeypatch):
    """Test that get_schedules returns ([], 0) on DB failure by default"""

    async def _boom(table_type, create_table_if_not_found=False):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(async_postgres_db, "_get_table", _boom)

    assert await async_postgres_db.get_schedules() == ([], 0)


@pytest.mark.asyncio
async def test_get_schedules_raise_on_error_reraises(async_postgres_db, monkeypatch):
    """Test that get_schedules(raise_on_error=True) re-raises DB failures"""

    async def _boom(table_type, create_table_if_not_found=False):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(async_postgres_db, "_get_table", _boom)

    with pytest.raises(RuntimeError, match="forced failure"):
        await async_postgres_db.get_schedules(raise_on_error=True)


@pytest.mark.asyncio
async def test_get_schedules_table_none_raises_under_flag(async_postgres_db, monkeypatch):
    """Test that an unavailable schedules table raises under raise_on_error=True"""

    async def _none(table_type, create_table_if_not_found=False):
        return None

    monkeypatch.setattr(async_postgres_db, "_get_table", _none)

    assert await async_postgres_db.get_schedules() == ([], 0)
    with pytest.raises(RuntimeError, match="schedules table unavailable"):
        await async_postgres_db.get_schedules(raise_on_error=True)


def _session_raising(error: Exception) -> Mock:
    """An async session factory whose execute() fails the way a live backend does."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=None)
    session.begin = Mock(return_value=session)
    session.execute = AsyncMock(side_effect=error)
    return Mock(return_value=session)


@pytest.mark.asyncio
async def test_delete_run_raises_on_a_backend_failure(async_postgres_db):
    """False means the run was not found. A dropped connection must not say that."""
    async_postgres_db._get_table = AsyncMock(return_value=Mock())
    async_postgres_db.async_session_factory = _session_raising(OSError("server closed the connection"))

    with pytest.raises(OSError, match="server closed"):
        await async_postgres_db.delete_run("run-1")


@pytest.mark.asyncio
async def test_delete_run_still_returns_false_when_there_is_no_such_run(async_postgres_db):
    """The meaning of False, pinned so it is not lost to the fix above."""
    async_postgres_db._get_table = AsyncMock(return_value=None)

    assert await async_postgres_db.delete_run("run-1") is False


@pytest.mark.asyncio
async def test_delete_runs_raises_on_a_backend_failure(async_postgres_db):
    async_postgres_db._get_table = AsyncMock(return_value=Mock())
    async_postgres_db.async_session_factory = _session_raising(OSError("server closed the connection"))

    with pytest.raises(OSError, match="server closed"):
        await async_postgres_db.delete_runs(["run-1", "run-2"])


@pytest.mark.asyncio
@pytest.mark.parametrize("lost_race_probe", [False, True])
async def test_cancelled_table_creation_can_be_retried(async_postgres_db, lost_race_probe):
    """Cancellation during creation, or during the lost-race probe, must unregister the table."""
    async_postgres_db.create_schema = False
    started = asyncio.Event()
    blocked = False

    class DuplicateTable(Exception):
        sqlstate = "42P07"

    probes = 0

    async def table_exists(table_name):
        nonlocal probes, blocked
        probes += 1
        if not blocked and probes == (2 if lost_race_probe else 1):
            blocked = True
            started.set()
            await asyncio.Event().wait()
        return False

    run_sync = AsyncMock(side_effect=[DuplicateTable(), None] if lost_race_probe else None)
    conn = Mock(run_sync=run_sync)
    begin_ctx = Mock(__aenter__=AsyncMock(return_value=conn), __aexit__=AsyncMock(return_value=None))
    async_postgres_db.db_engine.begin = Mock(return_value=begin_ctx)
    async_postgres_db.table_exists = table_exists
    async_postgres_db.upsert_schema_version = AsyncMock()

    task = asyncio.create_task(async_postgres_db._create_table("retry_table", "knowledge"))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not any(t.name == "retry_table" for t in async_postgres_db.metadata.tables.values())
    run_sync.side_effect = None
    table = await async_postgres_db._create_table("retry_table", "knowledge")
    assert table.name == "retry_table"
