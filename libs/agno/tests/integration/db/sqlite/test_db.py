"""Integration tests for the setup and main methods of the SqliteDb class"""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import text

from agno.db.sqlite.sqlite import SqliteDb


def test_init_with_db_url():
    """Test initialization with actual database URL format"""
    db_url = "sqlite:///:memory:"

    db = SqliteDb(db_url=db_url, session_table="test_sessions")
    assert db.db_url == db_url
    assert db.session_table_name == "test_sessions"

    # Test connection
    with db.Session() as sess:
        result = sess.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_create_session_table_integration(sqlite_db_real):
    """Test actual session table creation with SQLite"""
    # Create table
    sqlite_db_real._create_table("test_sessions", "sessions")

    # Verify table exists in database
    with sqlite_db_real.Session() as sess:
        result = sess.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name = :table"),
            {"table": "test_sessions"},
        )
        assert result.fetchone() is not None

    # Verify columns exist and have correct types using PRAGMA table_info
    with sqlite_db_real.Session() as sess:
        result = sess.execute(text("PRAGMA table_info(test_sessions)"))
        columns = {row[1]: {"type": row[2], "nullable": row[3] == 0} for row in result}

        # Verify key columns
        assert "session_id" in columns
        assert not columns["session_id"]["nullable"]  # PRIMARY KEY means NOT NULL
        assert "created_at" in columns
        assert "session_data" in columns


def test_create_metrics_table_with_constraints(sqlite_db_real):
    """Test creating metrics table with unique constraints"""
    sqlite_db_real._create_table("test_metrics", "metrics")

    # Verify unique constraint exists using SQLite's index listing
    with sqlite_db_real.Session() as sess:
        result = sess.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name = :table"),
            {"table": "test_metrics"},
        )
        table_sql = result.fetchone()[0]
        # Check that UNIQUE constraint exists in the table definition
        assert "UNIQUE" in table_sql or "PRIMARY KEY" in table_sql


def test_create_table_with_indexes(sqlite_db_real):
    """Test that indexes are created correctly"""
    sqlite_db_real._create_table("test_memories", "memories")

    # Verify indexes exist using SQLite's index listing
    with sqlite_db_real.Session() as sess:
        result = sess.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name = :table"),
            {"table": "test_memories"},
        )
        indexes = [row[0] for row in result]

        # Should have indexes on user_id and updated_at
        assert any("user_id" in idx for idx in indexes)
        assert any("updated_at" in idx for idx in indexes)


def test_get_table_with_create_table_if_not_found(sqlite_db_real):
    """Test getting a table with create_table_if_not_found=True"""
    table = sqlite_db_real._get_table("sessions", create_table_if_not_found=False)
    assert table is None

    table = sqlite_db_real._get_table("sessions", create_table_if_not_found=True)
    assert table is not None


def test_get_or_create_existing_table(sqlite_db_real):
    """Test getting an existing table"""
    # First create the table
    sqlite_db_real._create_table("test_sessions", "sessions")

    # Clear the cached table attribute
    if hasattr(sqlite_db_real, "session_table"):
        delattr(sqlite_db_real, "session_table")

    # Now get it again - should not recreate
    with patch.object(sqlite_db_real, "_create_table") as mock_create:
        table = sqlite_db_real._get_or_create_table("test_sessions", "sessions", create_table_if_not_found=True)

        # Should not call create since table exists
        mock_create.assert_not_called()

    assert table.name == "test_sessions"


def test_full_workflow(sqlite_db_real):
    """Test a complete workflow of creating and using tables"""
    # Get tables (will create them)
    session_table = sqlite_db_real._get_table("sessions", create_table_if_not_found=True)
    sqlite_db_real._get_table("memories", create_table_if_not_found=True)

    # Verify tables are cached
    assert hasattr(sqlite_db_real, "session_table")
    assert hasattr(sqlite_db_real, "memory_table")

    # Verify we can insert data (basic smoke test)
    with sqlite_db_real.Session() as sess:
        # Insert a test session
        sess.execute(
            session_table.insert().values(
                session_id="test-session-123",
                session_type="agent",
                created_at=int(datetime.now(timezone.utc).timestamp() * 1000),
                session_data={"test": "data"},
            )
        )
        sess.commit()

        # Query it back
        result = sess.execute(session_table.select().where(session_table.c.session_id == "test-session-123")).fetchone()

        assert result is not None
        assert result.session_type == "agent"
