"""Integration tests for the setup and main methods of the AsyncPostgresDb class"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from agno.db.postgres import AsyncPostgresDb


@pytest.mark.asyncio
async def test_init_with_db_url():
    """Test initialization with actual database URL format"""
    db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"

    db = AsyncPostgresDb(db_url=db_url, session_table="test_async_pg_sessions")
    assert db.db_url == db_url
    assert db.session_table_name == "test_async_pg_sessions"
    assert db.db_schema == "ai"

    # Test connection
    async with db.async_session_factory() as sess:
        result = await sess.execute(text("SELECT 1"))
        assert result.scalar() == 1

    await db.db_engine.dispose()


@pytest.mark.asyncio
async def test_create_session_table_integration(async_postgres_db_real):
    """Test actual session table creation with PostgreSQL"""
    # Create table
    await async_postgres_db_real._create_table("test_async_pg_sessions", "sessions")

    # Verify table exists in database with correct schema
    async with async_postgres_db_real.async_session_factory() as sess:
        result = await sess.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": "test_schema", "table": "test_async_pg_sessions"},
        )
        assert result.fetchone() is not None

    # Verify columns exist and have correct types
    async with async_postgres_db_real.async_session_factory() as sess:
        result = await sess.execute(
            text(
                "SELECT column_name, data_type, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table "
                "ORDER BY ordinal_position"
            ),
            {"schema": "test_schema", "table": "test_async_pg_sessions"},
        )
        rows = result.fetchall()
        columns = {row[0]: {"type": row[1], "nullable": row[2]} for row in rows}

        # Verify key columns
        assert "session_id" in columns
        assert columns["session_id"]["nullable"] == "NO"
        assert "created_at" in columns
        assert columns["created_at"]["type"] == "bigint"
        assert "session_data" in columns
        assert columns["session_data"]["type"] in ["json", "jsonb"]


@pytest.mark.asyncio
async def test_create_metrics_table_with_constraints(async_postgres_db_real):
    """Test creating metrics table with unique constraints"""
    await async_postgres_db_real._create_table("test_metrics", "metrics")

    # Verify unique constraint exists
    async with async_postgres_db_real.async_session_factory() as sess:
        result = await sess.execute(
            text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = :schema AND table_name = :table "
                "AND constraint_type = 'UNIQUE'"
            ),
            {"schema": "test_schema", "table": "test_metrics"},
        )
        rows = result.fetchall()
        constraints = [row[0] for row in rows]
        assert any("uq_metrics_date_period" in c for c in constraints)


@pytest.mark.asyncio
async def test_create_table_with_indexes(async_postgres_db_real):
    """Test that indexes are created correctly"""
    await async_postgres_db_real._create_table("test_memories", "memories")

    # Verify indexes exist
    async with async_postgres_db_real.async_session_factory() as sess:
        result = await sess.execute(
            text("SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND tablename = :table"),
            {"schema": "test_schema", "table": "test_memories"},
        )
        rows = result.fetchall()
        indexes = [row[0] for row in rows]

        # Should have indexes on user_id and updated_at
        assert any("user_id" in idx for idx in indexes)
        assert any("updated_at" in idx for idx in indexes)


@pytest.mark.asyncio
async def test_get_or_create_existing_table(async_postgres_db_real):
    """Test getting an existing table"""
    # First create the table
    await async_postgres_db_real._create_table("test_async_pg_sessions", "sessions")

    # Clear the cached table attribute
    if hasattr(async_postgres_db_real, "session_table"):
        delattr(async_postgres_db_real, "session_table")

    # Now get it again - should not recreate
    with patch.object(async_postgres_db_real, "_create_table", new=AsyncMock()) as mock_create:
        table = await async_postgres_db_real._get_or_create_table("test_async_pg_sessions", "sessions")

        # Should not call create since table exists
        mock_create.assert_not_called()

    assert table.name == "test_async_pg_sessions"


@pytest.mark.asyncio
async def test_full_workflow(async_postgres_db_real):
    """Test a complete workflow of creating and using tables"""
    # Get tables (will create them)
    session_table = await async_postgres_db_real._get_table("sessions", create_table_if_not_found=True)
    await async_postgres_db_real._get_table("memories", create_table_if_not_found=True)

    # Verify tables are cached
    assert hasattr(async_postgres_db_real, "session_table")
    assert hasattr(async_postgres_db_real, "memory_table")

    # Verify we can insert data (basic smoke test)
    async with async_postgres_db_real.async_session_factory() as sess:
        # Insert a test session
        await sess.execute(
            session_table.insert().values(
                session_id="test-session-123",
                session_type="agent",
                created_at=int(datetime.now(timezone.utc).timestamp() * 1000),
                session_data={"test": "data"},
            )
        )
        await sess.commit()

        # Query it back
        result = await sess.execute(session_table.select().where(session_table.c.session_id == "test-session-123"))
        row = result.fetchone()

        assert row is not None
        assert row.session_type == "agent"
