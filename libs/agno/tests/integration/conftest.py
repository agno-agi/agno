import os
import tempfile
import uuid

import pytest

from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory
from agno.storage.sqlite import SqliteStorage


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
def agent_storage(temp_storage_db_file):
    """Create a SQLite storage for agent sessions."""
    # Use a unique table name for each test run
    table_name = f"agent_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file)
    storage.create()
    return storage


@pytest.fixture
def team_storage(temp_storage_db_file):
    """Create a SQLite storage for team sessions."""
    # Use a unique table name for each test run
    table_name = f"team_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file, mode="team")
    storage.create()
    return storage


@pytest.fixture
def workflow_storage(temp_storage_db_file):
    """Create a SQLite storage for workflow sessions."""
    # Use a unique table name for each test run
    table_name = f"workflow_sessions_{uuid.uuid4().hex[:8]}"
    storage = SqliteStorage(table_name=table_name, db_file=temp_storage_db_file, mode="workflow")
    storage.create()
    return storage


@pytest.fixture
def memory_db(temp_memory_db_file):
    """Create a SQLite memory database for testing."""
    db = SqliteMemoryDb(db_file=temp_memory_db_file)
    db.create()
    return db


@pytest.fixture
def memory(memory_db):
    """Create a Memory instance for testing."""
    return Memory(db=memory_db)
