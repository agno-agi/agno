from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agno.db.postgres import AsyncPostgresDb


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    engine = Mock(spec=AsyncEngine)
    return engine


@pytest.fixture
def async_postgres_db(mock_async_engine) -> AsyncPostgresDb:
    """Create an AsyncPostgresDb instance with mock engine"""
    return AsyncPostgresDb(
        db_engine=mock_async_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


@pytest_asyncio.fixture
async def async_postgres_engine():
    """Create an async PostgreSQL engine for testing using the actual database setup"""
    # Use the same connection string but async version
    db_url = "postgresql+psycopg_async://ai:ai@localhost:5532/ai"
    engine = create_async_engine(db_url)

    # Test connection
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    yield engine

    # Cleanup: Drop schema after tests
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS test_schema CASCADE"))

    await engine.dispose()


@pytest_asyncio.fixture
async def async_postgres_db_real(async_postgres_engine) -> AsyncPostgresDb:
    """Create AsyncPostgresDb with real async PostgreSQL engine"""
    return AsyncPostgresDb(
        db_engine=async_postgres_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )
