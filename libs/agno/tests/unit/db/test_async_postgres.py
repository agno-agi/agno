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
