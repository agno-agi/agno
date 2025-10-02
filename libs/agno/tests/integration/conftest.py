import os
import tempfile
import uuid
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, create_engine, text

from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from agno.session import Session


@pytest.fixture
def temp_storage_db_file():
    """Create a temporary SQLite database file for agent storage testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def temp_memory_db_file():
    """Create a temporary SQLite database file for memory testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up the temporary file after the test
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def shared_db(temp_storage_db_file):
    """Create a SQLite storage for sessions."""
    # Use a unique table name for each test run
    table_name = f"sessions_{uuid.uuid4().hex[:8]}"
    db = SqliteDb(session_table=table_name, db_file=temp_storage_db_file)
    return db


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine"""
    engine = Mock(spec=Engine)
    return engine


@pytest.fixture
def mock_session():
    """Create a mock session"""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    return session


@pytest.fixture
def postgres_db(mock_engine) -> PostgresDb:
    """Create a PostgresDb instance with mock engine"""
    return PostgresDb(
        db_engine=mock_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


@pytest.fixture
def postgres_engine():
    """Create a PostgreSQL engine for testing using the actual database setup"""
    # Use the same connection string as the actual implementation
    db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
    engine = create_engine(db_url)

    # Test connection
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()

    yield engine

    # Cleanup: Drop schema after tests
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS test_schema CASCADE"))
        conn.commit()


@pytest.fixture
def postgres_db_real(postgres_engine) -> PostgresDb:
    """Create PostgresDb with real PostgreSQL engine"""
    return PostgresDb(
        db_engine=postgres_engine,
        db_schema="test_schema",
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )
