import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sqlite_db():
    from agno.db.sqlite.sqlite import SqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = SqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def async_sqlite_db():
    from agno.db.sqlite.async_sqlite import AsyncSqliteDb

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = AsyncSqliteDb(db_file=path)
    yield db
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def mock_postgres_db():
    from agno.db.postgres import PostgresDb

    mock_engine = MagicMock()
    mock_engine.url = "postgresql://test@localhost/test"
    db = PostgresDb(db_engine=mock_engine)
    return db


# ============================================================================
# SQLITE SYNC DELETE TESTS
# ============================================================================


def test_sqlite_delete_nonexistent_returns_false(sqlite_db):
    result = sqlite_db.delete_auth_token("google", "nonexistent_user", "gmail")
    assert result is False


def test_sqlite_delete_existing_token_returns_true(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user123",
            "service": "gmail",
            "token_data": {"access_token": "abc123"},
        }
    )

    result = sqlite_db.delete_auth_token("google", "user123", "gmail")
    assert result is True

    fetched = sqlite_db.get_auth_token("google", "user123", "gmail")
    assert fetched is None


def test_sqlite_delete_with_null_user_id(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": None,
            "service": "gmail",
            "token_data": {"token": "shared_token"},
        }
    )

    result = sqlite_db.delete_auth_token("google", None, "gmail")
    assert result is True

    fetched = sqlite_db.get_auth_token("google", None, "gmail")
    assert fetched is None


def test_sqlite_delete_only_affects_matching_row(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "user1_token"},
        }
    )
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user2",
            "service": "gmail",
            "token_data": {"token": "user2_token"},
        }
    )

    result = sqlite_db.delete_auth_token("google", "user1", "gmail")
    assert result is True

    user1 = sqlite_db.get_auth_token("google", "user1", "gmail")
    user2 = sqlite_db.get_auth_token("google", "user2", "gmail")

    assert user1 is None
    assert user2 is not None
    assert user2["token_data"]["token"] == "user2_token"


def test_sqlite_delete_requires_matching_provider(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "oauth",
            "token_data": {"token": "google_token"},
        }
    )

    result = sqlite_db.delete_auth_token("slack", "user1", "oauth")
    assert result is False

    google = sqlite_db.get_auth_token("google", "user1", "oauth")
    assert google is not None


def test_sqlite_delete_requires_matching_service(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "gmail_token"},
        }
    )

    result = sqlite_db.delete_auth_token("google", "user1", "drive")
    assert result is False

    gmail = sqlite_db.get_auth_token("google", "user1", "gmail")
    assert gmail is not None


# ============================================================================
# SQLITE ASYNC DELETE TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_async_sqlite_delete_nonexistent_returns_false(async_sqlite_db):
    result = await async_sqlite_db.delete_auth_token("google", "nonexistent", "gmail")
    assert result is False


@pytest.mark.asyncio
async def test_async_sqlite_delete_existing_returns_true(async_sqlite_db):
    await async_sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user123",
            "service": "gmail",
            "token_data": {"token": "test"},
        }
    )

    result = await async_sqlite_db.delete_auth_token("google", "user123", "gmail")
    assert result is True

    fetched = await async_sqlite_db.get_auth_token("google", "user123", "gmail")
    assert fetched is None


@pytest.mark.asyncio
async def test_async_sqlite_delete_with_null_user_id(async_sqlite_db):
    await async_sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": None,
            "service": "gmail",
            "token_data": {"token": "shared"},
        }
    )

    result = await async_sqlite_db.delete_auth_token("google", None, "gmail")
    assert result is True


# ============================================================================
# POSTGRES MOCKED DELETE TESTS
# ============================================================================


def test_postgres_delete_returns_false_when_table_missing(mock_postgres_db):
    with patch.object(mock_postgres_db, "_get_table", return_value=None):
        result = mock_postgres_db.delete_auth_token("google", "user1", "gmail")
        assert result is False


def test_postgres_delete_executes_delete_statement(mock_postgres_db):
    mock_table = MagicMock()
    mock_delete = MagicMock()
    mock_table.delete.return_value.where.return_value = mock_delete

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session.begin.return_value.__exit__ = MagicMock(return_value=None)

    mock_result = MagicMock()
    mock_result.rowcount = 1
    mock_session.execute.return_value = mock_result

    mock_postgres_db.Session = MagicMock(return_value=mock_session)

    with patch.object(mock_postgres_db, "_get_table", return_value=mock_table):
        result = mock_postgres_db.delete_auth_token("google", "user1", "gmail")

    assert result is True
    mock_session.execute.assert_called_once()


def test_postgres_delete_returns_false_on_no_rows_affected(mock_postgres_db):
    mock_table = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.begin.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_session.begin.return_value.__exit__ = MagicMock(return_value=None)

    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session.execute.return_value = mock_result

    mock_postgres_db.Session = MagicMock(return_value=mock_session)

    with patch.object(mock_postgres_db, "_get_table", return_value=mock_table):
        result = mock_postgres_db.delete_auth_token("google", "user1", "gmail")

    assert result is False
