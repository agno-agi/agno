"""Fixtures for sync MySQLDb integration tests."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import create_engine

from agno.db.mysql.mysql import MySQLDb


@pytest.fixture
def mysql_engine():
    """Create a sync MySQL engine for testing."""
    db_url = "mysql+pymysql://ai:ai@localhost:3306/ai"
    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture
def db(mysql_engine) -> MySQLDb:
    """Create MySQLDb with real MySQL engine."""
    return MySQLDb(
        db_engine=mysql_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
    )
