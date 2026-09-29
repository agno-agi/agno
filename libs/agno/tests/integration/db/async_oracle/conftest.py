import os
from unittest.mock import Mock

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from agno.db.oracle import AsyncOracleDb

# Start the local database with: ./cookbook/scripts/run_oracle.sh
# Override the URL (e.g. a different host port) with the ASYNC_ORACLE_TEST_URL env var.
ASYNC_ORACLE_TEST_URL = os.getenv(
    "ASYNC_ORACLE_TEST_URL", "oracle+oracledb_async://ai:ai@localhost:1521/?service_name=FREEPDB1"
)


@pytest.fixture
def mock_async_engine():
    """Create a mock async SQLAlchemy engine"""
    return Mock(spec=AsyncEngine)


@pytest.fixture
def async_oracle_db(mock_async_engine) -> AsyncOracleDb:
    """Create an AsyncOracleDb instance with mock engine"""
    return AsyncOracleDb(
        db_engine=mock_async_engine,
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


@pytest_asyncio.fixture
async def async_oracle_engine():
    """Create an async Oracle engine for testing using the local Docker database"""
    engine = create_async_engine(ASYNC_ORACLE_TEST_URL)

    # Test connection
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1 FROM dual"))

    yield engine

    # Cleanup: drop test tables after tests
    async with engine.begin() as conn:
        tables = (
            await conn.execute(text("SELECT table_name FROM user_tables WHERE table_name LIKE 'TEST\\_%' ESCAPE '\\'"))
        ).fetchall()
        for (table_name,) in tables:
            await conn.execute(text(f'DROP TABLE "{table_name}" CASCADE CONSTRAINTS PURGE'))

    await engine.dispose()


@pytest_asyncio.fixture
async def async_oracle_db_real(async_oracle_engine) -> AsyncOracleDb:
    """Create AsyncOracleDb with a real async Oracle engine"""
    return AsyncOracleDb(
        db_engine=async_oracle_engine,
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )
