"""Tests for v2.5.0 migration dispatch — verifies all DB type branches."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")

from agno.db.migrations.versions import v2_5_0  # noqa: E402


def _make_sync_db(class_name: str):
    """Create a mock sync DB whose type().__name__ returns the given class_name.

    We create an actual class instance (not MagicMock) so that type(db).__name__
    returns the correct class name. The class uses MagicMock for attribute access.
    """
    # Create a class that delegates attribute access to a MagicMock
    mock = MagicMock()

    class FakeDb:
        def __getattr__(self, name):
            return getattr(mock, name)

    # Rename the class to match the expected DB type
    FakeDb.__name__ = class_name
    FakeDb.__qualname__ = class_name
    return FakeDb()


def _make_async_db(class_name: str):
    """Create a mock async DB whose type().__name__ returns the given class_name.

    We create an actual class instance (not MagicMock) so that type(db).__name__
    returns the correct class name. The class uses MagicMock for attribute access.
    """
    # Create a class that delegates attribute access to a MagicMock
    mock = MagicMock()

    class FakeDb:
        def __getattr__(self, name):
            return getattr(mock, name)

    # Rename the class to match the expected DB type
    FakeDb.__name__ = class_name
    FakeDb.__qualname__ = class_name
    return FakeDb()


# ---------------------------------------------------------------------------
# Sync up() dispatch
# ---------------------------------------------------------------------------


class TestSyncUpDispatch:
    def test_non_sessions_table_returns_false(self):
        db = _make_sync_db("PostgresDb")
        assert v2_5_0.up(db, "non_sessions", "some_table") is False

    @patch.object(v2_5_0, "_migrate_postgres", return_value=True)
    def test_postgres_dispatches(self, mock_fn):
        db = _make_sync_db("PostgresDb")
        result = v2_5_0.up(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @patch.object(v2_5_0, "_migrate_mysql", return_value=True)
    def test_mysql_dispatches(self, mock_fn):
        db = _make_sync_db("MySQLDb")
        result = v2_5_0.up(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @patch.object(v2_5_0, "_migrate_singlestore", return_value=True)
    def test_singlestore_dispatches(self, mock_fn):
        db = _make_sync_db("SingleStoreDb")
        result = v2_5_0.up(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    def test_sqlite_returns_false(self):
        db = _make_sync_db("SqliteDb")
        assert v2_5_0.up(db, "sessions", "my_sessions") is False

    def test_unknown_db_returns_false(self):
        db = _make_sync_db("UnknownDb")
        assert v2_5_0.up(db, "sessions", "my_sessions") is False


# ---------------------------------------------------------------------------
# Async up() dispatch
# ---------------------------------------------------------------------------


class TestAsyncUpDispatch:
    @pytest.mark.asyncio
    async def test_non_sessions_table_returns_false(self):
        db = _make_async_db("AsyncPostgresDb")
        assert await v2_5_0.async_up(db, "non_sessions", "t") is False

    @pytest.mark.asyncio
    @patch.object(v2_5_0, "_migrate_async_postgres", new_callable=AsyncMock, return_value=True)
    async def test_async_postgres_dispatches(self, mock_fn):
        db = _make_async_db("AsyncPostgresDb")
        result = await v2_5_0.async_up(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @pytest.mark.asyncio
    @patch.object(v2_5_0, "_migrate_async_mysql", new_callable=AsyncMock, return_value=True)
    async def test_async_mysql_dispatches(self, mock_fn):
        db = _make_async_db("AsyncMySQLDb")
        result = await v2_5_0.async_up(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @pytest.mark.asyncio
    async def test_async_sqlite_returns_false(self):
        db = _make_async_db("AsyncSqliteDb")
        assert await v2_5_0.async_up(db, "sessions", "t") is False

    @pytest.mark.asyncio
    async def test_unknown_async_db_returns_false(self):
        db = _make_async_db("AsyncUnknownDb")
        assert await v2_5_0.async_up(db, "sessions", "t") is False


# ---------------------------------------------------------------------------
# Sync down() dispatch
# ---------------------------------------------------------------------------


class TestSyncDownDispatch:
    def test_non_sessions_table_returns_false(self):
        db = _make_sync_db("PostgresDb")
        assert v2_5_0.down(db, "non_sessions", "t") is False

    @patch.object(v2_5_0, "_revert_postgres", return_value=True)
    def test_postgres_dispatches(self, mock_fn):
        db = _make_sync_db("PostgresDb")
        result = v2_5_0.down(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @patch.object(v2_5_0, "_revert_mysql", return_value=True)
    def test_mysql_dispatches(self, mock_fn):
        db = _make_sync_db("MySQLDb")
        result = v2_5_0.down(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @patch.object(v2_5_0, "_revert_singlestore", return_value=True)
    def test_singlestore_dispatches(self, mock_fn):
        db = _make_sync_db("SingleStoreDb")
        result = v2_5_0.down(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    def test_sqlite_returns_false(self):
        db = _make_sync_db("SqliteDb")
        assert v2_5_0.down(db, "sessions", "t") is False


# ---------------------------------------------------------------------------
# Async down() dispatch
# ---------------------------------------------------------------------------


class TestAsyncDownDispatch:
    @pytest.mark.asyncio
    async def test_non_sessions_table_returns_false(self):
        db = _make_async_db("AsyncPostgresDb")
        assert await v2_5_0.async_down(db, "non_sessions", "t") is False

    @pytest.mark.asyncio
    @patch.object(v2_5_0, "_revert_async_postgres", new_callable=AsyncMock, return_value=True)
    async def test_async_postgres_dispatches(self, mock_fn):
        db = _make_async_db("AsyncPostgresDb")
        result = await v2_5_0.async_down(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @pytest.mark.asyncio
    @patch.object(v2_5_0, "_revert_async_mysql", new_callable=AsyncMock, return_value=True)
    async def test_async_mysql_dispatches(self, mock_fn):
        db = _make_async_db("AsyncMySQLDb")
        result = await v2_5_0.async_down(db, "sessions", "my_sessions")
        mock_fn.assert_called_once_with(db, "my_sessions")
        assert result is True

    @pytest.mark.asyncio
    async def test_async_sqlite_returns_false(self):
        db = _make_async_db("AsyncSqliteDb")
        assert await v2_5_0.async_down(db, "sessions", "t") is False
