"""Tests for span table schema with dynamic foreign key references."""

from unittest.mock import Mock, patch

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import Table

from agno.db.postgres.postgres import PostgresDb
from agno.db.postgres.schemas import get_table_schema_definition as get_postgres_schema
from agno.db.sqlite.schemas import get_table_schema_definition as get_sqlite_schema
from agno.db.sqlite.sqlite import SqliteDb

# ==================== SQLite Schema Tests ====================


def test_sqlite_span_schema_default_traces_table():
    """Test span schema uses default traces table name in foreign key."""
    schema = get_sqlite_schema("spans")

    assert "trace_id" in schema
    assert "foreign_key" in schema["trace_id"]
    assert schema["trace_id"]["foreign_key"] == "agno_traces.trace_id"


def test_sqlite_span_schema_custom_traces_table():
    """Test span schema uses custom traces table name in foreign key."""
    schema = get_sqlite_schema("spans", traces_table_name="custom_traces")

    assert "trace_id" in schema
    assert "foreign_key" in schema["trace_id"]
    assert schema["trace_id"]["foreign_key"] == "custom_traces.trace_id"


def test_sqlite_span_schema_has_required_columns():
    """Test span schema has all required columns."""
    schema = get_sqlite_schema("spans")

    expected_columns = [
        "span_id",
        "trace_id",
        "parent_span_id",
        "name",
        "span_kind",
        "status_code",
        "status_message",
        "start_time",
        "end_time",
        "duration_ms",
        "attributes",
        "created_at",
    ]
    for col in expected_columns:
        assert col in schema, f"Missing column: {col}"


def test_sqlite_span_schema_primary_key():
    """Test span_id is the primary key."""
    schema = get_sqlite_schema("spans")

    assert schema["span_id"]["primary_key"] is True


def test_sqlite_span_schema_indexes():
    """Test span schema has correct indexes."""
    schema = get_sqlite_schema("spans")

    # trace_id should be indexed for efficient joins
    assert schema["trace_id"]["index"] is True
    # parent_span_id should be indexed for tree traversal
    assert schema["parent_span_id"]["index"] is True
    # start_time and created_at should be indexed for time-based queries
    assert schema["start_time"]["index"] is True
    assert schema["created_at"]["index"] is True


# ==================== PostgreSQL Schema Tests ====================


def test_postgres_span_schema_default_values():
    """Test span schema uses default traces table and schema in foreign key."""
    schema = get_postgres_schema("spans")

    assert "trace_id" in schema
    assert "foreign_key" in schema["trace_id"]
    # Postgres includes schema prefix
    assert schema["trace_id"]["foreign_key"] == "agno.agno_traces.trace_id"


def test_postgres_span_schema_custom_traces_table():
    """Test span schema uses custom traces table name in foreign key."""
    schema = get_postgres_schema("spans", traces_table_name="my_traces")

    assert schema["trace_id"]["foreign_key"] == "agno.my_traces.trace_id"


def test_postgres_span_schema_custom_db_schema():
    """Test span schema uses custom database schema in foreign key."""
    schema = get_postgres_schema("spans", db_schema="custom_schema")

    assert schema["trace_id"]["foreign_key"] == "custom_schema.agno_traces.trace_id"


def test_postgres_span_schema_custom_both():
    """Test span schema uses both custom traces table and db schema."""
    schema = get_postgres_schema("spans", traces_table_name="my_traces", db_schema="my_schema")

    assert schema["trace_id"]["foreign_key"] == "my_schema.my_traces.trace_id"


def test_postgres_span_schema_has_required_columns():
    """Test span schema has all required columns."""
    schema = get_postgres_schema("spans")

    expected_columns = [
        "span_id",
        "trace_id",
        "parent_span_id",
        "name",
        "span_kind",
        "status_code",
        "status_message",
        "start_time",
        "end_time",
        "duration_ms",
        "attributes",
        "created_at",
    ]
    for col in expected_columns:
        assert col in schema, f"Missing column: {col}"


# ==================== SQLite Database Integration Tests ====================


@pytest.fixture
def sqlite_db_default(tmp_path):
    """Create a SqliteDb instance with default table names."""
    db_file = str(tmp_path / "test.db")
    return SqliteDb(
        db_file=db_file,
        traces_table="agno_traces",
        spans_table="agno_spans",
    )


@pytest.fixture
def sqlite_db_custom(tmp_path):
    """Create a SqliteDb instance with custom table names."""
    db_file = str(tmp_path / "test_custom.db")
    return SqliteDb(
        db_file=db_file,
        traces_table="custom_traces",
        spans_table="custom_spans",
    )


def test_sqlite_default_trace_table_name(sqlite_db_default):
    """Test default traces table name is used."""
    assert sqlite_db_default.trace_table_name == "agno_traces"


def test_sqlite_custom_trace_table_name(sqlite_db_custom):
    """Test custom traces table name is used."""
    assert sqlite_db_custom.trace_table_name == "custom_traces"


def test_sqlite_create_span_table_with_default_fk(sqlite_db_default):
    """Test span table creation uses default traces table in FK."""
    # Create traces table first (required for FK)
    sqlite_db_default._get_table(table_type="traces", create_table_if_not_found=True)

    # Create spans table
    table = sqlite_db_default._create_table("agno_spans", "spans")

    assert table is not None
    assert table.name == "agno_spans"

    # Verify foreign key references default traces table
    trace_id_col = table.c.trace_id
    assert len(trace_id_col.foreign_keys) == 1
    fk = list(trace_id_col.foreign_keys)[0]
    assert "agno_traces.trace_id" in str(fk.target_fullname)


def test_sqlite_create_span_table_with_custom_fk(sqlite_db_custom):
    """Test span table creation uses custom traces table in FK."""
    # Create traces table first (required for FK)
    sqlite_db_custom._get_table(table_type="traces", create_table_if_not_found=True)

    # Create spans table
    table = sqlite_db_custom._create_table("custom_spans", "spans")

    assert table is not None
    assert table.name == "custom_spans"

    # Verify foreign key references custom traces table
    trace_id_col = table.c.trace_id
    assert len(trace_id_col.foreign_keys) == 1
    fk = list(trace_id_col.foreign_keys)[0]
    assert "custom_traces.trace_id" in str(fk.target_fullname)


# ==================== PostgreSQL Database Integration Tests ====================


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine."""
    engine = Mock(spec=Engine)
    engine.url = "postgresql://fake:///url"
    return engine


@pytest.fixture
def mock_session():
    """Create a mock session."""
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    return session


@pytest.fixture
def postgres_db_default(mock_engine):
    """Create a PostgresDb instance with default table names."""
    return PostgresDb(
        db_engine=mock_engine,
        db_schema="ai",
        traces_table="agno_traces",
        spans_table="agno_spans",
    )


@pytest.fixture
def postgres_db_custom(mock_engine):
    """Create a PostgresDb instance with custom table names."""
    return PostgresDb(
        db_engine=mock_engine,
        db_schema="custom_schema",
        traces_table="custom_traces",
        spans_table="custom_spans",
    )


def test_postgres_default_trace_table_name(postgres_db_default):
    """Test default traces table name is used."""
    assert postgres_db_default.trace_table_name == "agno_traces"


def test_postgres_custom_trace_table_name(postgres_db_custom):
    """Test custom traces table name is used."""
    assert postgres_db_custom.trace_table_name == "custom_traces"


def test_postgres_custom_db_schema(postgres_db_custom):
    """Test custom db schema is used."""
    assert postgres_db_custom.db_schema == "custom_schema"


def test_postgres_create_span_table_with_default_fk(postgres_db_default, mock_session):
    """Test span table creation uses default traces table in FK."""
    postgres_db_default.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.postgres.postgres.create_schema"):
            with patch("agno.db.postgres.postgres.is_table_available", return_value=False):
                table = postgres_db_default._create_table("agno_spans", "spans")

    assert table is not None
    assert table.name == "agno_spans"

    # Verify foreign key references default traces table with schema
    trace_id_col = table.c.trace_id
    assert len(trace_id_col.foreign_keys) == 1
    fk = list(trace_id_col.foreign_keys)[0]
    # FK should reference ai.agno_traces.trace_id
    fk_target = str(fk.target_fullname)
    assert "agno_traces" in fk_target
    assert "trace_id" in fk_target


def test_postgres_create_span_table_with_custom_fk(postgres_db_custom, mock_session):
    """Test span table creation uses custom traces table and schema in FK."""
    postgres_db_custom.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.postgres.postgres.create_schema"):
            with patch("agno.db.postgres.postgres.is_table_available", return_value=False):
                table = postgres_db_custom._create_table("custom_spans", "spans")

    assert table is not None
    assert table.name == "custom_spans"

    # Verify foreign key references custom traces table with custom schema
    trace_id_col = table.c.trace_id
    assert len(trace_id_col.foreign_keys) == 1
    fk = list(trace_id_col.foreign_keys)[0]
    # FK should reference custom_schema.custom_traces.trace_id
    fk_target = str(fk.target_fullname)
    assert "custom_traces" in fk_target
    assert "trace_id" in fk_target


# ==================== Regression Tests ====================


def test_sqlite_span_fk_not_hardcoded():
    """Ensure SQLite span FK is not hardcoded to 'agno_traces'."""
    # Get schema with a different table name
    schema1 = get_sqlite_schema("spans", traces_table_name="table_a")
    schema2 = get_sqlite_schema("spans", traces_table_name="table_b")

    # FKs should be different
    assert schema1["trace_id"]["foreign_key"] != schema2["trace_id"]["foreign_key"]
    assert "table_a" in schema1["trace_id"]["foreign_key"]
    assert "table_b" in schema2["trace_id"]["foreign_key"]


def test_postgres_span_fk_not_hardcoded():
    """Ensure Postgres span FK is not hardcoded to 'agno.agno_traces'."""
    # Get schema with different table and schema names
    schema1 = get_postgres_schema("spans", traces_table_name="table_a", db_schema="schema_a")
    schema2 = get_postgres_schema("spans", traces_table_name="table_b", db_schema="schema_b")

    # FKs should be different
    assert schema1["trace_id"]["foreign_key"] != schema2["trace_id"]["foreign_key"]
    assert "schema_a.table_a" in schema1["trace_id"]["foreign_key"]
    assert "schema_b.table_b" in schema2["trace_id"]["foreign_key"]


def test_sqlite_span_fk_format():
    """Test SQLite span FK format is correct (no schema prefix)."""
    schema = get_sqlite_schema("spans", traces_table_name="my_traces")

    fk = schema["trace_id"]["foreign_key"]
    # SQLite doesn't use schema prefix
    assert fk == "my_traces.trace_id"
    # Should NOT have a schema prefix (no dots before table name)
    parts = fk.split(".")
    assert len(parts) == 2  # table.column


def test_postgres_span_fk_format():
    """Test Postgres span FK format is correct (with schema prefix)."""
    schema = get_postgres_schema("spans", traces_table_name="my_traces", db_schema="my_schema")

    fk = schema["trace_id"]["foreign_key"]
    # Postgres uses schema.table.column format
    assert fk == "my_schema.my_traces.trace_id"
    parts = fk.split(".")
    assert len(parts) == 3  # schema.table.column
