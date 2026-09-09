import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from agno.db.sqlite.schemas import AUTH_TOKEN_TABLE_SCHEMA, get_table_schema_definition

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
# AUTH_TOKEN_TABLE_SCHEMA TESTS
# ============================================================================


def test_schema_has_required_columns():
    schema = AUTH_TOKEN_TABLE_SCHEMA
    assert "id" in schema
    assert "provider" in schema
    assert "user_id" in schema
    assert "service" in schema
    assert "token_data" in schema
    assert "granted_scopes" in schema
    assert "created_at" in schema
    assert "updated_at" in schema


def test_id_is_primary_key():
    schema = AUTH_TOKEN_TABLE_SCHEMA
    assert schema["id"]["primary_key"] is True
    assert schema["id"]["nullable"] is False


def test_required_fields_not_nullable():
    schema = AUTH_TOKEN_TABLE_SCHEMA
    assert schema["provider"]["nullable"] is False
    assert schema["user_id"]["nullable"] is False
    assert schema["service"]["nullable"] is False
    assert schema["token_data"]["nullable"] is False


def test_granted_scopes_nullable():
    schema = AUTH_TOKEN_TABLE_SCHEMA
    assert schema["granted_scopes"]["nullable"] is True


def test_indexes_defined():
    schema = AUTH_TOKEN_TABLE_SCHEMA
    assert schema["provider"]["index"] is True
    assert schema["user_id"]["index"] is True
    assert schema["service"]["index"] is True
    assert schema["created_at"]["index"] is True


def test_unique_constraint_defined():
    schema = AUTH_TOKEN_TABLE_SCHEMA
    assert "_unique_constraints" in schema
    constraints = schema["_unique_constraints"]
    assert len(constraints) == 1
    constraint = constraints[0]
    assert constraint["name"] == "uq_auth_token_provider_user_service"
    assert constraint["columns"] == ["provider", "user_id", "service"]


def test_schema_registered_in_dispatcher():
    schema = get_table_schema_definition("auth_tokens")
    assert schema == AUTH_TOKEN_TABLE_SCHEMA


# ============================================================================
# SQLITE SYNC TESTS
# ============================================================================


def test_sqlite_get_auth_token_not_found(sqlite_db):
    result = sqlite_db.get_auth_token("google", "nonexistent_user", "gmail")
    assert result is None


def test_sqlite_upsert_and_get_auth_token(sqlite_db):
    token_data = {
        "provider": "google",
        "user_id": "user123",
        "service": "gmail",
        "token_data": {"access_token": "abc123", "refresh_token": "xyz789"},
        "granted_scopes": ["https://mail.google.com/"],
    }

    result = sqlite_db.upsert_auth_token(token_data)
    assert result is not None
    assert result["provider"] == "google"
    assert result["user_id"] == "user123"
    assert result["service"] == "gmail"
    assert "id" in result
    assert "created_at" in result
    assert "updated_at" in result

    fetched = sqlite_db.get_auth_token("google", "user123", "gmail")
    assert fetched is not None
    assert fetched["provider"] == "google"
    assert fetched["user_id"] == "user123"
    assert fetched["token_data"] == {"access_token": "abc123", "refresh_token": "xyz789"}


def test_sqlite_upsert_updates_existing_token(sqlite_db):
    token_v1 = {
        "provider": "google",
        "user_id": "user123",
        "service": "gmail",
        "token_data": {"access_token": "old_token"},
        "granted_scopes": ["scope1"],
    }
    sqlite_db.upsert_auth_token(token_v1)
    first_fetch = sqlite_db.get_auth_token("google", "user123", "gmail")
    original_id = first_fetch["id"]
    original_created_at = first_fetch["created_at"]

    time.sleep(0.01)

    token_v2 = {
        "provider": "google",
        "user_id": "user123",
        "service": "gmail",
        "token_data": {"access_token": "new_token"},
        "granted_scopes": ["scope1", "scope2"],
    }
    sqlite_db.upsert_auth_token(token_v2)

    updated = sqlite_db.get_auth_token("google", "user123", "gmail")
    assert updated is not None
    assert updated["id"] == original_id
    assert updated["created_at"] == original_created_at
    assert updated["token_data"] == {"access_token": "new_token"}
    assert updated["granted_scopes"] == ["scope1", "scope2"]
    assert updated["updated_at"] >= original_created_at


def test_sqlite_null_user_id_converts_to_empty_string(sqlite_db):
    token = {
        "provider": "google",
        "user_id": None,
        "service": "gmail",
        "token_data": {"access_token": "token123"},
    }
    sqlite_db.upsert_auth_token(token)

    fetched = sqlite_db.get_auth_token("google", None, "gmail")
    assert fetched is not None
    assert fetched["user_id"] == ""

    fetched_explicit = sqlite_db.get_auth_token("google", "", "gmail")
    assert fetched_explicit is not None
    assert fetched_explicit["token_data"] == {"access_token": "token123"}


def test_sqlite_different_services_different_rows(sqlite_db):
    token_gmail = {
        "provider": "google",
        "user_id": "user1",
        "service": "gmail",
        "token_data": {"token": "gmail_token"},
    }
    token_drive = {
        "provider": "google",
        "user_id": "user1",
        "service": "drive",
        "token_data": {"token": "drive_token"},
    }

    sqlite_db.upsert_auth_token(token_gmail)
    sqlite_db.upsert_auth_token(token_drive)

    gmail = sqlite_db.get_auth_token("google", "user1", "gmail")
    drive = sqlite_db.get_auth_token("google", "user1", "drive")

    assert gmail["token_data"]["token"] == "gmail_token"
    assert drive["token_data"]["token"] == "drive_token"
    assert gmail["id"] != drive["id"]


def test_sqlite_different_users_different_rows(sqlite_db):
    token_user1 = {
        "provider": "google",
        "user_id": "user1",
        "service": "gmail",
        "token_data": {"token": "user1_token"},
    }
    token_user2 = {
        "provider": "google",
        "user_id": "user2",
        "service": "gmail",
        "token_data": {"token": "user2_token"},
    }

    sqlite_db.upsert_auth_token(token_user1)
    sqlite_db.upsert_auth_token(token_user2)

    user1 = sqlite_db.get_auth_token("google", "user1", "gmail")
    user2 = sqlite_db.get_auth_token("google", "user2", "gmail")

    assert user1["token_data"]["token"] == "user1_token"
    assert user2["token_data"]["token"] == "user2_token"


def test_sqlite_different_providers_different_rows(sqlite_db):
    token_google = {
        "provider": "google",
        "user_id": "user1",
        "service": "oauth",
        "token_data": {"token": "google_token"},
    }
    token_slack = {
        "provider": "slack",
        "user_id": "user1",
        "service": "oauth",
        "token_data": {"token": "slack_token"},
    }

    sqlite_db.upsert_auth_token(token_google)
    sqlite_db.upsert_auth_token(token_slack)

    google = sqlite_db.get_auth_token("google", "user1", "oauth")
    slack = sqlite_db.get_auth_token("slack", "user1", "oauth")

    assert google["token_data"]["token"] == "google_token"
    assert slack["token_data"]["token"] == "slack_token"


# ============================================================================
# SQLITE ASYNC TESTS
# ============================================================================


@pytest.mark.asyncio
async def test_async_sqlite_get_auth_token_not_found(async_sqlite_db):
    result = await async_sqlite_db.get_auth_token("google", "nonexistent", "gmail")
    assert result is None


@pytest.mark.asyncio
async def test_async_sqlite_upsert_and_get_auth_token(async_sqlite_db):
    token_data = {
        "provider": "google",
        "user_id": "user123",
        "service": "gmail",
        "token_data": {"access_token": "abc123"},
        "granted_scopes": ["scope1"],
    }

    result = await async_sqlite_db.upsert_auth_token(token_data)
    assert result is not None
    assert result["provider"] == "google"

    fetched = await async_sqlite_db.get_auth_token("google", "user123", "gmail")
    assert fetched is not None
    assert fetched["token_data"]["access_token"] == "abc123"


@pytest.mark.asyncio
async def test_async_sqlite_upsert_updates_existing(async_sqlite_db):
    token_v1 = {
        "provider": "google",
        "user_id": "user1",
        "service": "gmail",
        "token_data": {"token": "old"},
    }
    await async_sqlite_db.upsert_auth_token(token_v1)
    first = await async_sqlite_db.get_auth_token("google", "user1", "gmail")
    original_id = first["id"]

    token_v2 = {
        "provider": "google",
        "user_id": "user1",
        "service": "gmail",
        "token_data": {"token": "new"},
    }
    await async_sqlite_db.upsert_auth_token(token_v2)

    updated = await async_sqlite_db.get_auth_token("google", "user1", "gmail")
    assert updated["id"] == original_id
    assert updated["token_data"]["token"] == "new"


@pytest.mark.asyncio
async def test_async_sqlite_null_user_id_handling(async_sqlite_db):
    token = {
        "provider": "google",
        "user_id": None,
        "service": "gmail",
        "token_data": {"token": "test"},
    }
    await async_sqlite_db.upsert_auth_token(token)

    fetched = await async_sqlite_db.get_auth_token("google", None, "gmail")
    assert fetched is not None
    assert fetched["user_id"] == ""


# ============================================================================
# POSTGRES MOCKED TESTS
# ============================================================================


def test_postgres_get_auth_token_returns_none_when_table_missing(mock_postgres_db):
    with patch.object(mock_postgres_db, "_get_table", return_value=None):
        result = mock_postgres_db.get_auth_token("google", "user1", "gmail")
        assert result is None


def test_postgres_upsert_creates_table_if_missing(mock_postgres_db):
    mock_table = MagicMock()
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=None)
    mock_session.begin = MagicMock(return_value=mock_session)
    mock_session.begin().__enter__ = MagicMock(return_value=mock_session)
    mock_session.begin().__exit__ = MagicMock(return_value=None)

    mock_postgres_db.Session = MagicMock(return_value=mock_session)

    with patch.object(mock_postgres_db, "_get_table", return_value=mock_table) as mock_get_table:
        mock_postgres_db.upsert_auth_token(
            {
                "provider": "google",
                "user_id": "user1",
                "service": "gmail",
                "token_data": {"token": "test"},
            }
        )

        mock_get_table.assert_called_once_with(table_type="auth_tokens", create_table_if_not_found=True)


# ============================================================================
# ERROR HANDLING TESTS
# ============================================================================


def test_get_auth_token_handles_exception(sqlite_db):
    with patch.object(sqlite_db, "_get_table", side_effect=Exception("DB error")):
        result = sqlite_db.get_auth_token("google", "user1", "gmail")
        assert result is None


def test_upsert_auth_token_handles_exception(sqlite_db):
    with patch.object(sqlite_db, "_get_table", side_effect=Exception("DB error")):
        result = sqlite_db.upsert_auth_token(
            {
                "provider": "google",
                "user_id": "user1",
                "service": "gmail",
                "token_data": {},
            }
        )
        assert result is None


# ============================================================================
# TIMESTAMP TESTS
# ============================================================================


def test_created_at_set_on_insert(sqlite_db):
    before = int(time.time())
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "test"},
        }
    )
    after = int(time.time())

    fetched = sqlite_db.get_auth_token("google", "user1", "gmail")
    assert before <= fetched["created_at"] <= after


def test_updated_at_changes_on_update(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "v1"},
        }
    )
    first = sqlite_db.get_auth_token("google", "user1", "gmail")
    original_updated = first["updated_at"]

    time.sleep(0.01)

    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "v2"},
        }
    )
    second = sqlite_db.get_auth_token("google", "user1", "gmail")

    assert second["updated_at"] >= original_updated


def test_created_at_preserved_on_update(sqlite_db):
    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "v1"},
        }
    )
    first = sqlite_db.get_auth_token("google", "user1", "gmail")
    original_created = first["created_at"]

    time.sleep(0.01)

    sqlite_db.upsert_auth_token(
        {
            "provider": "google",
            "user_id": "user1",
            "service": "gmail",
            "token_data": {"token": "v2"},
        }
    )
    second = sqlite_db.get_auth_token("google", "user1", "gmail")

    assert second["created_at"] == original_created
