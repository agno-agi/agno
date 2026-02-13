"""Tests for database migration endpoints in AgentOS."""

import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import BigInteger, Column, MetaData, String, Table, text
from sqlalchemy.engine import create_engine
from sqlalchemy.types import JSON

from agno.agent.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS


def create_old_schema_memory_table(db_file: str, table_name: str) -> None:
    """Create a memory table with the old schema (v2.0.0) - without created_at and feedback columns."""
    engine = create_engine(f"sqlite:///{db_file}")
    metadata = MetaData()

    # Old schema - without created_at and feedback columns
    Table(
        table_name,
        metadata,
        Column("memory_id", String, primary_key=True, nullable=False),
        Column("memory", JSON, nullable=False),
        Column("input", String, nullable=True),
        Column("agent_id", String, nullable=True),
        Column("team_id", String, nullable=True),
        Column("user_id", String, nullable=True),
        Column("topics", JSON, nullable=True),
        Column("updated_at", BigInteger, nullable=True),
    )

    metadata.create_all(engine)
    engine.dispose()


def create_versions_table_with_old_version(db_file: str, table_name: str, memory_table_name: str) -> None:
    """Create a versions table and set the memory table version to 2.0.0."""
    engine = create_engine(f"sqlite:///{db_file}")
    metadata = MetaData()

    versions_table = Table(
        table_name,
        metadata,
        Column("table_name", String, primary_key=True, nullable=False),
        Column("version", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("updated_at", String, nullable=True),
    )

    metadata.create_all(engine)

    # Insert old version record for memory table
    with engine.connect() as conn:
        conn.execute(
            versions_table.insert().values(
                table_name=memory_table_name,
                version="2.0.0",
                created_at=str(int(time.time())),
                updated_at=None,
            )
        )
        conn.commit()

    engine.dispose()


def get_memory_table_columns(db_file: str, table_name: str) -> set:
    """Get the column names from the memory table."""
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        columns = {row[1] for row in result.fetchall()}
    engine.dispose()
    return columns


def get_schema_version(db: SqliteDb, table_name: str) -> str:
    """Get the schema version for a table."""
    return db.get_latest_schema_version(table_name)


@pytest.fixture
def temp_db_file():
    """Create a temporary SQLite database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_file:
        db_path = temp_file.name

    yield db_path

    # Clean up
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def old_schema_dbs(temp_db_file):
    """Create multiple SqliteDb instances with old schema pointing to the same file."""
    # Create old schema tables for each agent
    memory_tables = ["agent1_memories", "agent2_memories", "agent3_memories"]
    versions_table = "agno_versions"

    for memory_table in memory_tables:
        create_old_schema_memory_table(temp_db_file, memory_table)

    # Create versions table with old versions for each memory table
    engine = create_engine(f"sqlite:///{temp_db_file}")
    metadata = MetaData()

    versions_table_obj = Table(
        versions_table,
        metadata,
        Column("table_name", String, primary_key=True, nullable=False),
        Column("version", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("updated_at", String, nullable=True),
    )
    metadata.create_all(engine)

    with engine.connect() as conn:
        for memory_table in memory_tables:
            conn.execute(
                versions_table_obj.insert().values(
                    table_name=memory_table,
                    version="2.0.0",
                    created_at=str(int(time.time())),
                    updated_at=None,
                )
            )
        conn.commit()
    engine.dispose()

    # Create SqliteDb instances
    db1 = SqliteDb(
        db_file=temp_db_file,
        id="db-1",
        memory_table="agent1_memories",
        session_table="agent1_sessions",
    )
    db2 = SqliteDb(
        db_file=temp_db_file,
        id="db-2",
        memory_table="agent2_memories",
        session_table="agent2_sessions",
    )
    db3 = SqliteDb(
        db_file=temp_db_file,
        id="db-3",
        memory_table="agent3_memories",
        session_table="agent3_sessions",
    )

    return {
        "db_file": temp_db_file,
        "dbs": [db1, db2, db3],
        "memory_tables": memory_tables,
    }


@pytest.fixture
def os_client_with_old_schema_dbs(old_schema_dbs):
    """Create an AgentOS with multiple agents having different DBs with old schema."""
    dbs = old_schema_dbs["dbs"]

    agent1 = Agent(name="agent-1", id="agent-1-id", db=dbs[0])
    agent2 = Agent(name="agent-2", id="agent-2-id", db=dbs[1])
    agent3 = Agent(name="agent-3", id="agent-3-id", db=dbs[2])

    agent_os = AgentOS(
        id="test-os",
        agents=[agent1, agent2, agent3],
    )
    app = agent_os.get_app()
    client = TestClient(app)

    return {
        "client": client,
        "db_file": old_schema_dbs["db_file"],
        "dbs": dbs,
        "memory_tables": old_schema_dbs["memory_tables"],
        "agent_os": agent_os,
    }


def test_migrate_single_db_success(os_client_with_old_schema_dbs):
    """Test successfully migrating a single database."""
    client = os_client_with_old_schema_dbs["client"]
    dbs = os_client_with_old_schema_dbs["dbs"]
    db_file = os_client_with_old_schema_dbs["db_file"]
    memory_tables = os_client_with_old_schema_dbs["memory_tables"]

    # Verify old schema - no created_at or feedback columns
    columns_before = get_memory_table_columns(db_file, memory_tables[0])
    assert "created_at" not in columns_before
    assert "feedback" not in columns_before

    # Verify old version
    version_before = get_schema_version(dbs[0], memory_tables[0])
    assert version_before == "2.0.0"

    # Migrate the first database
    response = client.post(f"/databases/{dbs[0].id}/migrate")
    assert response.status_code == 200
    assert "migrated successfully" in response.json()["message"]

    # Verify new schema - created_at and feedback columns should exist
    columns_after = get_memory_table_columns(db_file, memory_tables[0])
    assert "created_at" in columns_after
    assert "feedback" in columns_after

    # Verify new version
    version_after = get_schema_version(dbs[0], memory_tables[0])
    assert version_after == "2.5.0"

    # Other databases should still be at old version
    version_db2 = get_schema_version(dbs[1], memory_tables[1])
    assert version_db2 == "2.0.0"


def test_migrate_single_db_not_found(os_client_with_old_schema_dbs):
    """Test migrating a non-existent database returns 404."""
    client = os_client_with_old_schema_dbs["client"]

    response = client.post("/databases/non-existent-db/migrate")
    assert response.status_code == 404
    assert response.json()["detail"] == "No database found with id 'non-existent-db'"


def test_migrate_single_db_to_specific_version(os_client_with_old_schema_dbs):
    """Test migrating a database to a specific version."""
    client = os_client_with_old_schema_dbs["client"]
    dbs = os_client_with_old_schema_dbs["dbs"]
    memory_tables = os_client_with_old_schema_dbs["memory_tables"]

    # Migrate to version 2.3.0 explicitly
    response = client.post(f"/databases/{dbs[0].id}/migrate?target_version=2.3.0")
    assert response.status_code == 200

    # Verify version
    version_after = get_schema_version(dbs[0], memory_tables[0])
    assert version_after == "2.3.0"


def test_migrate_all_dbs_success(os_client_with_old_schema_dbs):
    """Test successfully migrating all databases."""
    client = os_client_with_old_schema_dbs["client"]
    dbs = os_client_with_old_schema_dbs["dbs"]
    db_file = os_client_with_old_schema_dbs["db_file"]
    memory_tables = os_client_with_old_schema_dbs["memory_tables"]

    # Verify all databases are at old version
    for i, db in enumerate(dbs):
        version = get_schema_version(db, memory_tables[i])
        assert version == "2.0.0", f"DB {i} should be at version 2.0.0"

        columns = get_memory_table_columns(db_file, memory_tables[i])
        assert "created_at" not in columns
        assert "feedback" not in columns

    # Migrate all databases
    response = client.post("/databases/all/migrate")
    assert response.status_code == 200
    assert "All databases migrated successfully" in response.json()["message"]

    # Verify all databases are now at new version
    for i, db in enumerate(dbs):
        version = get_schema_version(db, memory_tables[i])
        assert version == "2.5.0", f"DB {i} should be at version 2.5.0"

        columns = get_memory_table_columns(db_file, memory_tables[i])
        assert "created_at" in columns
        assert "feedback" in columns


def test_migrate_all_dbs_to_specific_version(os_client_with_old_schema_dbs):
    """Test migrating all databases to a specific version."""
    client = os_client_with_old_schema_dbs["client"]
    dbs = os_client_with_old_schema_dbs["dbs"]
    memory_tables = os_client_with_old_schema_dbs["memory_tables"]

    # Migrate all to 2.3.0
    response = client.post("/databases/all/migrate?target_version=2.3.0")
    assert response.status_code == 200

    # Verify all are at 2.3.0
    for i, db in enumerate(dbs):
        version = get_schema_version(db, memory_tables[i])
        assert version == "2.3.0"


def test_migrate_all_dbs_partial_failure(temp_db_file):
    """Test that migration continues even if one database fails."""
    # Create two DBs - one with old schema, one that will fail
    memory_table_good = "good_memories"
    memory_table_bad = "bad_memories"
    versions_table = "agno_versions"

    # Create good old schema table
    create_old_schema_memory_table(temp_db_file, memory_table_good)

    # Create versions table
    engine = create_engine(f"sqlite:///{temp_db_file}")
    metadata = MetaData()
    versions_table_obj = Table(
        versions_table,
        metadata,
        Column("table_name", String, primary_key=True, nullable=False),
        Column("version", String, nullable=False),
        Column("created_at", String, nullable=False),
        Column("updated_at", String, nullable=True),
    )
    metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(
            versions_table_obj.insert().values(
                table_name=memory_table_good,
                version="2.0.0",
                created_at=str(int(time.time())),
                updated_at=None,
            )
        )
        # Set bad table to old version but don't create the table
        conn.execute(
            versions_table_obj.insert().values(
                table_name=memory_table_bad,
                version="2.0.0",
                created_at=str(int(time.time())),
                updated_at=None,
            )
        )
        conn.commit()
    engine.dispose()

    db_good = SqliteDb(
        db_file=temp_db_file,
        id="db-good",
        memory_table=memory_table_good,
        session_table="good_sessions",
    )
    db_bad = SqliteDb(
        db_file=temp_db_file,
        id="db-bad",
        memory_table=memory_table_bad,  # Table doesn't exist
        session_table="bad_sessions",
    )

    agent_good = Agent(name="agent-good", id="agent-good-id", db=db_good)
    agent_bad = Agent(name="agent-bad", id="agent-bad-id", db=db_bad)

    agent_os = AgentOS(id="test-os", agents=[agent_good, agent_bad])
    app = agent_os.get_app()
    client = TestClient(app)

    # Migrate all - should continue even if one fails
    response = client.post("/databases/all/migrate")

    # Should return 207 Multi-Status when some fail
    # Or 200 if the bad table is just skipped without error
    assert response.status_code in [200, 207]

    # The good database should still be migrated
    version_good = get_schema_version(db_good, memory_table_good)
    assert version_good == "2.5.0"

    columns = get_memory_table_columns(temp_db_file, memory_table_good)
    assert "created_at" in columns
    assert "feedback" in columns


def test_migrate_already_migrated_db(os_client_with_old_schema_dbs):
    """Test that migrating an already migrated database is idempotent."""
    client = os_client_with_old_schema_dbs["client"]
    dbs = os_client_with_old_schema_dbs["dbs"]
    memory_tables = os_client_with_old_schema_dbs["memory_tables"]

    # First migration
    response1 = client.post(f"/databases/{dbs[0].id}/migrate")
    assert response1.status_code == 200

    version_after_first = get_schema_version(dbs[0], memory_tables[0])
    assert version_after_first == "2.5.0"

    # Second migration - should succeed without errors
    response2 = client.post(f"/databases/{dbs[0].id}/migrate")
    assert response2.status_code == 200

    version_after_second = get_schema_version(dbs[0], memory_tables[0])
    assert version_after_second == "2.5.0"
