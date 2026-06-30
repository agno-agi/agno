from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import Index, Table, UniqueConstraint

from agno.db.postgres.postgres import PostgresDb
from agno.db.postgres.schemas import (
    EVAL_TABLE_SCHEMA,
    KNOWLEDGE_TABLE_SCHEMA,
    MEMORY_TABLE_SCHEMA,
    METRICS_TABLE_SCHEMA,
    SESSION_TABLE_SCHEMA,
    get_table_schema_definition,
)
from agno.db.utils import json_serializer


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine"""
    engine = Mock(spec=Engine)
    engine.url = "fake:///url"
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
def postgres_db(mock_engine):
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


def test_id_is_deterministic(mock_engine):
    # Initialize two databases with the same engine
    first_db = PostgresDb(db_engine=mock_engine)
    second_db = PostgresDb(db_engine=mock_engine)

    # Assert that the ids are the same
    assert first_db.id == second_db.id


def test_init_with_engine(mock_engine):
    """Test initialization with engine"""
    db = PostgresDb(db_engine=mock_engine, session_table="sessions")

    assert db.db_engine == mock_engine
    assert db.db_schema == "ai"
    assert db.session_table_name == "sessions"


@patch("agno.db.postgres.postgres.create_engine")
def test_init_with_url(mock_create_engine):
    """Test initialization with database URL"""
    mock_engine = Mock(spec=Engine)
    mock_create_engine.return_value = mock_engine

    db = PostgresDb(db_url="postgresql://user:pass@localhost/db", session_table="sessions")

    mock_create_engine.assert_called_once_with(
        "postgresql://user:pass@localhost/db",
        pool_pre_ping=True,
        pool_recycle=3600,
        json_serializer=json_serializer,
    )
    assert db.db_engine == mock_engine


def test_init_no_engine_or_url():
    """Test initialization fails without engine or URL"""
    with pytest.raises(ValueError, match="One of db_url or db_engine must be provided"):
        PostgresDb(session_table="sessions")


def test_init_no_tables(mock_engine):
    """Test initialization works when not specifying any tables"""
    PostgresDb(db_engine=mock_engine)


def test_create_table(postgres_db, mock_session):
    """Test table creation"""
    postgres_db.Session = Mock(return_value=mock_session)

    # Mock table creation
    with patch.object(Table, "create") as mock_table_create:
        with patch("agno.db.postgres.postgres.create_schema") as mock_create_schema:
            with patch("agno.db.postgres.postgres.is_table_available", return_value=False):
                table = postgres_db._create_table("test_sessions", "sessions")

    # Verify schema was created
    mock_create_schema.assert_called()

    # Verify table creation
    mock_table_create.assert_called_with(postgres_db.db_engine, checkfirst=True)

    # Verify table has correct structure
    assert table.name == "test_sessions"
    assert table.schema == "test_schema"

    # Verify columns exist
    column_names = [col.name for col in table.columns]
    expected_columns = [
        "session_id",
        "session_type",
        "agent_id",
        "team_id",
        "workflow_id",
        "user_id",
        "session_data",
        "agent_data",
        "team_data",
        "workflow_data",
        "metadata",
        "runs",
        "summary",
        "created_at",
        "updated_at",
    ]
    for col in expected_columns:
        assert col in column_names


def test_create_table_with_indexes(postgres_db, mock_session):
    """Test table creation with indexes"""
    postgres_db.Session = Mock(return_value=mock_session)
    mock_session.execute.return_value.scalar.return_value = None

    with patch.object(Table, "create"):
        with patch.object(Index, "create"):
            with patch("agno.db.postgres.postgres.create_schema"):
                table = postgres_db._create_table("test_metrics", "metrics")

    # Verify table has indexes on date and created_at columns
    for index in table.indexes:
        column = index.columns[0]
        assert column.name == "date"


def test_create_table_with_unique_constraints(postgres_db, mock_session):
    """Test table creation with unique constraints"""
    postgres_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.postgres.postgres.create_schema"):
            table = postgres_db._create_table("test_metrics", "metrics")

    # Verify unique constraint was added
    constraint_names = [c.name for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert "test_metrics_uq_metrics_date_period" in constraint_names

    # Verify the constraint has the correct columns
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint.name == "test_metrics_uq_metrics_date_period":
            col_names = [col.name for col in constraint.columns]
            assert "date" in col_names
            assert "aggregation_period" in col_names


def test_create_memory_table(postgres_db, mock_session):
    """Test creation of memory table with correct schema"""
    postgres_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.postgres.postgres.create_schema"):
            table = postgres_db._create_table("test_memories", "memories")

    # Verify primary key
    pk_columns = [col.name for col in table.columns if col.primary_key]
    assert "memory_id" in pk_columns

    # Verify indexed columns
    indexed_columns = []
    for index in table.indexes:
        for column in index.columns:
            indexed_columns.append(column.name)
    assert set(indexed_columns) == {"user_id", "created_at", "updated_at"}


def test_create_eval_table(postgres_db, mock_session):
    """Test creation of eval table with correct schema"""
    postgres_db.Session = Mock(return_value=mock_session)

    with patch("agno.db.postgres.schemas.get_table_schema_definition") as mock_get_schema:
        mock_get_schema.return_value = EVAL_TABLE_SCHEMA.copy()

        with patch.object(Table, "create"):
            table = postgres_db._create_table("test_evals", "evals")

        # Verify columns
        column_names = [col.name for col in table.columns]
        assert "run_id" in column_names
        assert "eval_type" in column_names
        assert "eval_data" in column_names

        # Verify primary key
        pk_columns = [col.name for col in table.columns if col.primary_key]
        assert "run_id" in pk_columns


def test_create_knowledge_table(postgres_db, mock_session):
    """Test creation of knowledge table with correct schema"""
    postgres_db.Session = Mock(return_value=mock_session)

    with patch("agno.db.postgres.schemas.get_table_schema_definition") as mock_get_schema:
        mock_get_schema.return_value = KNOWLEDGE_TABLE_SCHEMA.copy()

        with patch.object(Table, "create"):
            table = postgres_db._create_table("test_knowledge", "knowledge")

        # Verify columns
        column_names = [col.name for col in table.columns]
        expected_columns = [
            "id",
            "name",
            "description",
            "metadata",
            "type",
            "size",
            "linked_to",
            "access_count",
            "created_at",
            "updated_at",
            "status",
            "status_message",
        ]
        for col in expected_columns:
            assert col in column_names


def test_get_table_sessions(postgres_db):
    """Test getting sessions table"""
    mock_table = Mock(spec=Table)

    with patch.object(postgres_db, "_get_or_create_table", return_value=mock_table):
        table = postgres_db._get_table("sessions")

    assert table == mock_table
    assert hasattr(postgres_db, "session_table")


def test_get_table_memories(postgres_db):
    """Test getting memories table"""
    mock_table = Mock(spec=Table)

    with patch.object(postgres_db, "_get_or_create_table", return_value=mock_table):
        table = postgres_db._get_table("memories")

    assert table == mock_table
    assert hasattr(postgres_db, "memory_table")


def test_get_table_metrics(postgres_db):
    """Test getting metrics table"""
    mock_table = Mock(spec=Table)

    with patch.object(postgres_db, "_get_or_create_table", return_value=mock_table):
        table = postgres_db._get_table("metrics")

    assert table == mock_table
    assert hasattr(postgres_db, "metrics_table")


def test_get_table_evals(postgres_db):
    """Test getting evals table"""
    mock_table = Mock(spec=Table)

    with patch.object(postgres_db, "_get_or_create_table", return_value=mock_table):
        table = postgres_db._get_table("evals")

    assert table == mock_table
    assert hasattr(postgres_db, "eval_table")


def test_get_table_knowledge(postgres_db):
    """Test getting knowledge table"""
    mock_table = Mock(spec=Table)

    with patch.object(postgres_db, "_get_or_create_table", return_value=mock_table):
        table = postgres_db._get_table("knowledge")

    assert table == mock_table
    assert hasattr(postgres_db, "knowledge_table")


def test_get_table_invalid_type(postgres_db):
    """Test getting table with invalid type"""
    with pytest.raises(ValueError, match="Unknown table type"):
        postgres_db._get_table("invalid_type")


@patch("agno.db.postgres.postgres.is_table_available")
@patch("agno.db.postgres.postgres.is_valid_table")
def test_get_or_create_table_existing_valid(mock_is_valid, mock_is_available, postgres_db, mock_session):
    """Test getting existing valid table"""
    mock_is_available.return_value = True
    mock_is_valid.return_value = True

    postgres_db.Session = Mock(return_value=mock_session)

    mock_table = Mock(spec=Table)
    with patch.object(Table, "__new__", return_value=mock_table):
        table = postgres_db._get_or_create_table("test_table", "sessions", "test_schema")

    assert table == mock_table
    mock_is_available.assert_called_once()
    mock_is_valid.assert_called_once()


@patch("agno.db.postgres.postgres.is_table_available")
def test_get_or_create_table_not_available(mock_is_available, postgres_db, mock_session):
    """Test creating table when not available"""
    mock_is_available.return_value = False
    postgres_db.Session = Mock(return_value=mock_session)
    postgres_db.upsert_schema_version = Mock(return_value=None)

    mock_table = Mock(spec=Table)
    with patch.object(postgres_db, "_create_table", return_value=mock_table):
        table = postgres_db._get_or_create_table(
            table_name="test_table", table_type="sessions", create_table_if_not_found=True
        )
        assert table == mock_table
        postgres_db._create_table.assert_called_once_with(table_name="test_table", table_type="sessions")


@patch("agno.db.postgres.postgres.is_table_available")
@patch("agno.db.postgres.postgres.is_valid_table")
def test_get_or_create_table_invalid_schema(mock_is_valid, mock_is_available, postgres_db, mock_session):
    """Test error when table exists but has invalid schema"""
    mock_is_available.return_value = True
    mock_is_valid.return_value = False

    postgres_db.Session = Mock(return_value=mock_session)

    with pytest.raises(ValueError, match="has an invalid schema"):
        postgres_db._get_or_create_table("test_table", "sessions", "test_schema")


@patch("agno.db.postgres.postgres.is_table_available")
@patch("agno.db.postgres.postgres.is_valid_table")
def test_get_or_create_table_load_error(mock_is_valid, mock_is_available, postgres_db, mock_session):
    """Test error when loading existing table fails"""
    mock_is_available.return_value = True
    mock_is_valid.return_value = True

    postgres_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "__new__", side_effect=Exception("Load error")):
        with pytest.raises(Exception):
            postgres_db._get_or_create_table("test_table", "sessions", "test_schema")


def test_get_table_schema_definition_sessions():
    """Test getting session table schema"""
    schema = get_table_schema_definition("sessions")
    assert schema == SESSION_TABLE_SCHEMA
    assert "session_id" in schema
    assert schema["session_id"]["nullable"] is False
    assert schema["session_id"]["primary_key"] is True


def test_get_table_schema_definition_memories():
    """Test getting memory table schema"""
    schema = get_table_schema_definition("memories")
    assert schema == MEMORY_TABLE_SCHEMA
    assert "memory_id" in schema
    assert schema["memory_id"]["primary_key"] is True


def test_get_table_schema_definition_evals():
    """Test getting eval table schema"""
    schema = get_table_schema_definition("evals")
    assert schema == EVAL_TABLE_SCHEMA
    assert "run_id" in schema
    assert schema["eval_type"]["nullable"] is False


def test_get_table_schema_definition_knowledge():
    """Test getting knowledge table schema"""
    schema = get_table_schema_definition("knowledge")
    assert schema == KNOWLEDGE_TABLE_SCHEMA
    assert "id" in schema
    assert schema["name"]["nullable"] is False


def test_get_table_schema_definition_metrics():
    """Test getting metrics table schema"""
    schema = get_table_schema_definition("metrics")
    assert schema == METRICS_TABLE_SCHEMA
    assert "date" in schema
    assert schema["date"]["index"] is True
    assert "_unique_constraints" in schema


def test_get_table_schema_definition_invalid():
    """Test getting schema for invalid table type"""
    with pytest.raises(ValueError, match="Unknown table type"):
        get_table_schema_definition("invalid_table")
