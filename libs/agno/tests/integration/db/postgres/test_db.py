"""Integration tests for the setup and main methods of the PostgresDb class"""

from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import text

from agno.db.postgres.postgres import PostgresDb


def test_init_with_db_url():
    """Test initialization with actual database URL format"""
    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"

    db = PostgresDb(db_url=db_url, session_table="test_sessions")
    assert db.db_url == db_url
    assert db.session_table_name == "test_sessions"
    assert db.db_schema == "ai"

    # Test connection
    with db.Session() as sess:
        result = sess.execute(text("SELECT 1"))
        assert result.scalar() == 1


def test_create_session_table_integration(postgres_db_real):
    """Test actual session table creation with PostgreSQL"""
    # Create table
    postgres_db_real._create_table("test_sessions", "sessions")

    # Verify table exists in database with correct schema
    with postgres_db_real.Session() as sess:
        result = sess.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": "test_schema", "table": "test_sessions"},
        )
        assert result.fetchone() is not None

    # Verify columns exist and have correct types
    with postgres_db_real.Session() as sess:
        result = sess.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"schema": "test_schema", "table": "test_sessions"},
        )
        columns = {row[0]: {"type": row[1], "nullable": row[2]} for row in result}

        # Verify key columns
        assert "session_id" in columns
        assert columns["session_id"]["nullable"] == "NO"
        assert "created_at" in columns
        assert columns["created_at"]["type"] == "bigint"
        assert "session_data" in columns
        assert columns["session_data"]["type"] in ["json", "jsonb"]


def test_create_metrics_table_with_constraints(postgres_db_real):
    """Test creating metrics table with unique constraints"""
    postgres_db_real._create_table("test_metrics", "metrics")

    # Verify unique constraint exists
    with postgres_db_real.Session() as sess:
        result = sess.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_type = 'UNIQUE'"
            ),
            {"schema": "test_schema", "table": "test_metrics"},
        )
        constraints = [row[0] for row in result]
        assert any("uq_metrics_date_period" in c for c in constraints)


def test_create_table_with_indexes(postgres_db_real):
    """Test that indexes are created correctly"""
    postgres_db_real._create_table("test_memories", "memories")

    # Verify indexes exist
    with postgres_db_real.Session() as sess:
        result = sess.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND tablename = :table"),
            {"schema": "test_schema", "table": "test_memories"},
        )
        indexes = [row[0] for row in result]

        # Should have indexes on user_id and updated_at
        assert any("user_id" in idx for idx in indexes)
        assert any("updated_at" in idx for idx in indexes)


def test_get_table_with_create_table_if_not_found(postgres_db_real):
    """Test getting a table with create_table_if_not_found=True"""
    table = postgres_db_real._get_table("sessions", create_table_if_not_found=False)
    assert table is None

    table = postgres_db_real._get_table("sessions", create_table_if_not_found=True)
    assert table is not None


def test_get_or_create_existing_table(postgres_db_real):
    """Test getting an existing table"""
    # First create the table
    postgres_db_real._create_table("test_sessions", "sessions")

    # Clear the cached table attribute
    if hasattr(postgres_db_real, "session_table"):
        delattr(postgres_db_real, "session_table")

    # Now get it again - should not recreate
    with patch.object(postgres_db_real, "_create_table") as mock_create:
        table = postgres_db_real._get_or_create_table("test_sessions", "sessions")

        # Should not call create since table exists
        mock_create.assert_not_called()

    assert table.name == "test_sessions"


def test_full_workflow(postgres_db_real):
    """Test a complete workflow of creating and using tables"""
    # Get tables (will create them)
    session_table = postgres_db_real._get_table("sessions", create_table_if_not_found=True)
    postgres_db_real._get_table("memories", create_table_if_not_found=True)

    # Verify tables are cached
    assert hasattr(postgres_db_real, "session_table")
    assert hasattr(postgres_db_real, "memory_table")

    # Verify we can insert data (basic smoke test)
    with postgres_db_real.Session() as sess:
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
