import os

import pytest
from sqlalchemy import create_engine, text

from agno.db.oracle import OracleDb

# Start the local database with: ./cookbook/scripts/run_oracle.sh
# Override the URL (e.g. a different host port) with the ORACLE_TEST_URL env var.
ORACLE_TEST_URL = os.getenv("ORACLE_TEST_URL", "oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1")


def _drop_test_tables(engine) -> None:
    """Drop every TEST_% table owned by the connected user."""
    with engine.connect() as conn:
        tables = conn.execute(
            text("SELECT table_name FROM user_tables WHERE table_name LIKE 'TEST\\_%' ESCAPE '\\'")
        ).fetchall()
        for (table_name,) in tables:
            conn.execute(text(f'DROP TABLE "{table_name}" CASCADE CONSTRAINTS PURGE'))
        conn.commit()


@pytest.fixture
def oracle_engine():
    """Create an Oracle engine for testing using the local Docker database"""
    engine = create_engine(ORACLE_TEST_URL)

    # Test connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 FROM dual"))

    yield engine

    # Cleanup: drop test tables after tests
    _drop_test_tables(engine)
    engine.dispose()


@pytest.fixture
def oracle_db_real(oracle_engine) -> OracleDb:
    """Create OracleDb with a real Oracle engine"""
    return OracleDb(
        db_engine=oracle_engine,
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )
