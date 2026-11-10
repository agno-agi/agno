from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agno.db.mysql import AsyncMySQLDb


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    engine = Mock(spec=AsyncEngine)
    return engine


@pytest.fixture
def async_mysql_db(mock_async_engine) -> AsyncMySQLDb:
    """Create an AsyncMySQLDb instance with mock engine"""
    return AsyncMySQLDb(
        db_engine=mock_async_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


@pytest_asyncio.fixture
async def async_mysql_engine():
    """Create an async MySQL engine for testing using the actual database setup"""
    # Use the asyncmy driver for async MySQL connections
    db_url = "mysql+asyncmy://ai:ai@localhost:3306/ai"
    engine = create_async_engine(db_url)

    # Test connection
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))

    yield engine

    # Cleanup: Drop schema after tests
    async with engine.begin() as conn:
        await conn.execute(text("DROP DATABASE IF EXISTS test_schema"))

    await engine.dispose()


@pytest_asyncio.fixture
async def async_mysql_db_real(async_mysql_engine) -> AsyncMySQLDb:
    """Create AsyncMySQLDb with real async MySQL engine"""
    return AsyncMySQLDb(
        db_engine=async_mysql_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )
