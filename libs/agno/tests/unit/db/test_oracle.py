import inspect
import json
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import MetaData, select
from sqlalchemy.dialects import oracle as oracle_dialect_module
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import Column, Index, Table, UniqueConstraint
from sqlalchemy.types import BigInteger, Date, String

from agno.db.oracle import oracle as oracle_module
from agno.db.oracle import schemas as oracle_schemas_module
from agno.db.oracle import utils as oracle_utils_module
from agno.db.oracle.oracle import OracleDb
from agno.db.oracle.schemas import (
    CULTURAL_KNOWLEDGE_TABLE_SCHEMA,
    EVAL_TABLE_SCHEMA,
    KNOWLEDGE_TABLE_SCHEMA,
    METRICS_TABLE_SCHEMA,
    SESSION_TABLE_SCHEMA,
    TRACE_TABLE_SCHEMA,
    USER_MEMORY_TABLE_SCHEMA,
    VERSIONS_TABLE_SCHEMA,
    OracleJSON,
    get_table_schema_definition,
)
from agno.db.oracle.utils import (
    apply_sorting,
    build_merge_stmt,
    deserialize_cultural_knowledge_from_db,
    is_table_available,
    is_valid_table,
    merge_upsert,
    serialize_cultural_knowledge_for_db,
    validate_schema_exists,
)
from agno.db.schemas.culture import CulturalKnowledge

ORACLE_DIALECT = oracle_dialect_module.dialect()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_engine():
    """Create a mock SQLAlchemy engine"""
    engine = Mock(spec=Engine)
    engine.url = "oracle+oracledb://fake:fake@localhost:1521/?service_name=FREEPDB1"
    return engine


@pytest.fixture
def mock_session():
    """Create a mock session.

    ``get_bind().dialect`` is set to a real Oracle dialect (not a plain Mock) because
    ``OracleDb._create_table`` always ends by stamping the schema version via
    ``merge_upsert``, which needs a real dialect's identifier preparer to quote and
    build the MERGE statement text eagerly.
    """
    session = Mock(spec=Session)
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=None)
    session.begin = Mock()
    session.begin().__enter__ = Mock(return_value=session)
    session.begin().__exit__ = Mock(return_value=None)
    session.get_bind.return_value.dialect = ORACLE_DIALECT
    return session


@pytest.fixture
def oracle_db(mock_engine):
    """Create an OracleDb instance with mock engine, no custom schema (user's own schema)"""
    return OracleDb(
        db_engine=mock_engine,
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )


def _make_table(name: str = "test_sessions", schema=None, columns=None) -> Table:
    """Build a small, real SQLAlchemy Table for utils-level tests (no engine/connection involved)."""
    metadata = MetaData(schema=schema)
    if columns is None:
        columns = [
            Column("session_id", String(128), primary_key=True),
            Column("session_type", String(20)),
            Column("created_at", BigInteger),
        ]
    return Table(name, metadata, *columns, schema=schema)


# ---------------------------------------------------------------------------
# Group: construction / table lifecycle
# ---------------------------------------------------------------------------


def test_id_is_deterministic(mock_engine):
    """Test that two instances with the same engine and schema get the same id"""
    first_db = OracleDb(db_engine=mock_engine)
    second_db = OracleDb(db_engine=mock_engine)

    assert first_db.id == second_db.id


def test_id_differs_by_schema(mock_engine):
    """Test that the id changes when db_schema changes, since Oracle schemas are users"""
    default_schema_db = OracleDb(db_engine=mock_engine)
    custom_schema_db = OracleDb(db_engine=mock_engine, db_schema="ai")

    assert default_schema_db.id != custom_schema_db.id


def test_init_with_engine(mock_engine):
    """Test initialization with engine defaults db_schema to None (the connected user's schema)"""
    db = OracleDb(db_engine=mock_engine, session_table="sessions")

    assert db.db_engine == mock_engine
    assert db.db_schema is None
    assert db.session_table_name == "sessions"


@patch("agno.db.oracle.oracle.create_engine")
def test_init_with_url(mock_create_engine):
    """Test initialization with database URL. The Oracle dialect accepts no json_serializer
    kwarg (JSON serialization lives in the OracleJSON column type) and no pool kwargs."""
    mock_engine = Mock(spec=Engine)
    mock_create_engine.return_value = mock_engine

    db = OracleDb(
        db_url="oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1",
        session_table="sessions",
    )

    mock_create_engine.assert_called_once_with(
        "oracle+oracledb://ai:ai@localhost:1521/?service_name=FREEPDB1",
    )
    assert db.db_engine == mock_engine


def test_init_no_engine_or_url():
    """Test initialization fails without engine or URL"""
    with pytest.raises(ValueError, match="One of db_url or db_engine must be provided"):
        OracleDb(session_table="sessions")


def test_init_no_tables(mock_engine):
    """Test initialization works when not specifying any tables, falling back to agno_* defaults"""
    db = OracleDb(db_engine=mock_engine)

    assert db.session_table_name == "agno_sessions"
    assert db.culture_table_name == "agno_culture"
    assert db.memory_table_name == "agno_memories"
    assert db.metrics_table_name == "agno_metrics"
    assert db.eval_table_name == "agno_eval_runs"
    assert db.knowledge_table_name == "agno_knowledge"
    assert db.trace_table_name == "agno_traces"
    assert db.span_table_name == "agno_spans"
    assert db.versions_table_name == "agno_schema_versions"


def test_create_table(oracle_db, mock_session):
    """Test table creation with no db_schema (Oracle default: connected user's schema)"""
    oracle_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create") as mock_table_create:
        with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
            table = oracle_db._create_table("test_sessions", "sessions")

    # Verify table creation
    mock_table_create.assert_called_with(oracle_db.db_engine, checkfirst=True)

    # Verify table has correct structure
    assert table.name == "test_sessions"
    assert table.schema is None

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


def test_create_table_with_db_schema_validates_existence(mock_engine, mock_session):
    """Test that create_table validates schema (user) existence when db_schema is set.

    Note: creating "test_sessions" also bootstraps the schema-versions table (to stamp
    the new table's schema version), which triggers its own validation call, so
    validate_schema_exists is called at least once, not necessarily exactly once.
    """
    db = OracleDb(db_engine=mock_engine, db_schema="ai", session_table="test_sessions")
    db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.oracle.oracle.validate_schema_exists") as mock_validate_schema:
            with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
                table = db._create_table("test_sessions", "sessions")

    mock_validate_schema.assert_called()
    for call in mock_validate_schema.call_args_list:
        assert call.kwargs["db_schema"] == "ai"
    assert table.schema == "ai"


def test_create_table_skips_schema_validation_when_create_schema_false(mock_engine, mock_session):
    """Test that schema validation is skipped when create_schema=False, even with db_schema set"""
    db = OracleDb(db_engine=mock_engine, db_schema="ai", create_schema=False, session_table="test_sessions")
    db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.oracle.oracle.validate_schema_exists") as mock_validate_schema:
            with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
                db._create_table("test_sessions", "sessions")

    mock_validate_schema.assert_not_called()


def test_create_table_skips_schema_validation_when_schema_none(oracle_db, mock_session):
    """Test that schema validation is skipped when db_schema is None (connected user's own schema)"""
    oracle_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.oracle.oracle.validate_schema_exists") as mock_validate_schema:
            with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
                oracle_db._create_table("test_sessions", "sessions")

    mock_validate_schema.assert_not_called()


def test_create_table_with_indexes(oracle_db, mock_session):
    """Test table creation with indexes"""
    oracle_db.Session = Mock(return_value=mock_session)
    mock_session.execute.return_value.scalar.return_value = None

    with patch.object(Table, "create"):
        with patch.object(Index, "create"):
            with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
                table = oracle_db._create_table("test_metrics", "metrics")

    # Verify table has indexes on the date column
    for index in table.indexes:
        column = index.columns[0]
        assert column.name == "date"


def test_create_table_with_unique_constraints(oracle_db, mock_session):
    """Test table creation with unique constraints"""
    oracle_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
            table = oracle_db._create_table("test_metrics", "metrics")

    # Verify unique constraint was added
    constraint_names = [c.name for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert "test_metrics_uq_metrics_date_period" in constraint_names

    # Verify the constraint has the correct columns
    for constraint in table.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint.name == "test_metrics_uq_metrics_date_period":
            col_names = [col.name for col in constraint.columns]
            assert "date" in col_names
            assert "aggregation_period" in col_names


def test_create_memory_table(oracle_db, mock_session):
    """Test creation of memory table with correct schema"""
    oracle_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "create"):
        with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
            table = oracle_db._create_table("test_memories", "memories")

    # Verify primary key
    pk_columns = [col.name for col in table.columns if col.primary_key]
    assert "memory_id" in pk_columns

    # Verify indexed columns
    indexed_columns = []
    for index in table.indexes:
        for column in index.columns:
            indexed_columns.append(column.name)
    assert set(indexed_columns) == {"user_id", "created_at", "updated_at"}


def test_create_eval_table(oracle_db, mock_session):
    """Test creation of eval table with correct schema"""
    oracle_db.Session = Mock(return_value=mock_session)

    with patch("agno.db.oracle.schemas.get_table_schema_definition") as mock_get_schema:
        mock_get_schema.return_value = EVAL_TABLE_SCHEMA.copy()

        with patch.object(Table, "create"):
            with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
                table = oracle_db._create_table("test_evals", "evals")

        # Verify columns
        column_names = [col.name for col in table.columns]
        assert "run_id" in column_names
        assert "eval_type" in column_names
        assert "eval_data" in column_names

        # Verify primary key
        pk_columns = [col.name for col in table.columns if col.primary_key]
        assert "run_id" in pk_columns


def test_create_knowledge_table(oracle_db, mock_session):
    """Test creation of knowledge table with correct schema"""
    oracle_db.Session = Mock(return_value=mock_session)

    with patch("agno.db.oracle.schemas.get_table_schema_definition") as mock_get_schema:
        mock_get_schema.return_value = KNOWLEDGE_TABLE_SCHEMA.copy()

        with patch.object(Table, "create"):
            with patch("agno.db.oracle.oracle.is_table_available", return_value=False):
                table = oracle_db._create_table("test_knowledge", "knowledge")

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
            "external_id",
        ]
        for col in expected_columns:
            assert col in column_names


def test_get_table_sessions(oracle_db):
    """Test getting sessions table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("sessions")

    assert table == mock_table
    assert hasattr(oracle_db, "session_table")


def test_get_table_memories(oracle_db):
    """Test getting memories table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("memories")

    assert table == mock_table
    assert hasattr(oracle_db, "memory_table")


def test_get_table_metrics(oracle_db):
    """Test getting metrics table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("metrics")

    assert table == mock_table
    assert hasattr(oracle_db, "metrics_table")


def test_get_table_evals(oracle_db):
    """Test getting evals table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("evals")

    assert table == mock_table
    assert hasattr(oracle_db, "eval_table")


def test_get_table_knowledge(oracle_db):
    """Test getting knowledge table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("knowledge")

    assert table == mock_table
    assert hasattr(oracle_db, "knowledge_table")


def test_get_table_culture(oracle_db):
    """Test getting culture table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("culture")

    assert table == mock_table
    assert hasattr(oracle_db, "culture_table")


def test_get_table_versions(oracle_db):
    """Test getting versions table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("versions")

    assert table == mock_table
    assert hasattr(oracle_db, "versions_table")


def test_get_table_traces(oracle_db):
    """Test getting traces table"""
    mock_table = Mock(spec=Table)

    with patch.object(oracle_db, "_get_or_create_table", return_value=mock_table):
        table = oracle_db._get_table("traces")

    assert table == mock_table
    assert hasattr(oracle_db, "traces_table")


def test_get_table_spans_creates_traces_first(oracle_db):
    """Test that requesting the spans table creates the traces table first (FK dependency)"""
    mock_table = Mock(spec=Table)
    calls = []

    def fake_get_or_create_table(table_name, table_type, create_table_if_not_found=False):
        calls.append(table_type)
        return mock_table

    with patch.object(oracle_db, "_get_or_create_table", side_effect=fake_get_or_create_table):
        table = oracle_db._get_table("spans", create_table_if_not_found=True)

    assert table == mock_table
    assert calls == ["traces", "spans"]
    assert hasattr(oracle_db, "spans_table")


def test_get_table_spans_skips_traces_bootstrap_when_not_creating(oracle_db):
    """Test that requesting the spans table without create_table_if_not_found does not bootstrap traces"""
    mock_table = Mock(spec=Table)
    calls = []

    def fake_get_or_create_table(table_name, table_type, create_table_if_not_found=False):
        calls.append(table_type)
        return mock_table

    with patch.object(oracle_db, "_get_or_create_table", side_effect=fake_get_or_create_table):
        oracle_db._get_table("spans", create_table_if_not_found=False)

    assert calls == ["spans"]


def test_get_table_invalid_type(oracle_db):
    """Test getting table with invalid type"""
    with pytest.raises(ValueError, match="Unknown table type"):
        oracle_db._get_table("invalid_type")


@patch("agno.db.oracle.oracle.is_table_available")
@patch("agno.db.oracle.oracle.is_valid_table")
def test_get_or_create_table_existing_valid(mock_is_valid, mock_is_available, oracle_db, mock_session):
    """An existing valid table is rebuilt from the schema definition, not reflected.

    Reflection (autoload_with) loses the OracleJSON column type, which breaks JSON
    serialization on the raw MERGE binds (DPY-3002).
    """
    mock_is_available.return_value = True
    mock_is_valid.return_value = True

    oracle_db.Session = Mock(return_value=mock_session)

    mock_table = Mock(spec=Table)
    with patch.object(oracle_db, "_create_table", return_value=mock_table) as mock_create:
        table = oracle_db._get_or_create_table("test_table", "sessions")

    assert table == mock_table
    mock_is_available.assert_called_once()
    mock_is_valid.assert_called_once()
    mock_create.assert_called_once_with(table_name="test_table", table_type="sessions")


@patch("agno.db.oracle.oracle.is_table_available")
def test_get_or_create_table_not_available(mock_is_available, oracle_db, mock_session):
    """Test creating table when not available"""
    mock_is_available.return_value = False
    oracle_db.Session = Mock(return_value=mock_session)
    oracle_db.upsert_schema_version = Mock(return_value=None)

    mock_table = Mock(spec=Table)
    with patch.object(oracle_db, "_create_table", return_value=mock_table):
        table = oracle_db._get_or_create_table(
            table_name="test_table", table_type="sessions", create_table_if_not_found=True
        )
        assert table == mock_table
        oracle_db._create_table.assert_called_once_with(table_name="test_table", table_type="sessions")


@patch("agno.db.oracle.oracle.is_table_available")
def test_get_or_create_table_not_available_no_create(mock_is_available, oracle_db, mock_session):
    """Test that the table is not created when create_table_if_not_found is False"""
    mock_is_available.return_value = False
    oracle_db.Session = Mock(return_value=mock_session)

    with patch.object(oracle_db, "_create_table") as mock_create_table:
        table = oracle_db._get_or_create_table(
            table_name="test_table", table_type="sessions", create_table_if_not_found=False
        )

    assert table is None
    mock_create_table.assert_not_called()


@patch("agno.db.oracle.oracle.is_table_available")
@patch("agno.db.oracle.oracle.is_valid_table")
def test_get_or_create_table_invalid_schema(mock_is_valid, mock_is_available, oracle_db, mock_session):
    """Test error when table exists but has invalid schema"""
    mock_is_available.return_value = True
    mock_is_valid.return_value = False

    oracle_db.Session = Mock(return_value=mock_session)

    with pytest.raises(ValueError, match="has an invalid schema"):
        oracle_db._get_or_create_table("test_table", "sessions")


@patch("agno.db.oracle.oracle.is_table_available")
@patch("agno.db.oracle.oracle.is_valid_table")
def test_get_or_create_table_load_error(mock_is_valid, mock_is_available, oracle_db, mock_session):
    """Test error when loading existing table fails"""
    mock_is_available.return_value = True
    mock_is_valid.return_value = True

    oracle_db.Session = Mock(return_value=mock_session)

    with patch.object(Table, "__new__", side_effect=Exception("Load error")):
        with pytest.raises(Exception):
            oracle_db._get_or_create_table("test_table", "sessions")


# ---------------------------------------------------------------------------
# Group: schemas (agno/db/oracle/schemas.py)
# ---------------------------------------------------------------------------


def test_get_table_schema_definition_sessions():
    """Test the sessions schema has the expected Oracle column definitions"""
    schema = get_table_schema_definition("sessions")
    assert schema == SESSION_TABLE_SCHEMA
    assert schema["session_id"]["primary_key"] is True
    assert schema["session_id"]["nullable"] is False
    assert isinstance(schema["session_id"]["type"](), String)
    assert schema["session_type"]["index"] is True
    assert schema["created_at"]["index"] is True
    assert schema["created_at"]["type"] is BigInteger
    assert schema["session_data"]["type"] is OracleJSON


def test_oracle_json_type_round_trips_values():
    """Test OracleJSON serializes binds to JSON text and deserializes results back,
    for dicts, lists and plain strings alike (the Oracle dialect has no native JSON)"""
    json_type = OracleJSON()

    for value in ({"a": 1, "b": [2, 3]}, ["x", "y"], "a plain string"):
        bound = json_type.process_bind_param(value, ORACLE_DIALECT)
        assert bound == json.dumps(value)
        assert json_type.process_result_value(bound, ORACLE_DIALECT) == value


def test_oracle_json_type_passes_none_through():
    """Test OracleJSON maps None to SQL NULL and back (never the 'null' JSON string)"""
    json_type = OracleJSON()

    assert json_type.process_bind_param(None, ORACLE_DIALECT) is None
    assert json_type.process_result_value(None, ORACLE_DIALECT) is None


def test_oracle_json_type_renders_clob_ddl():
    """Test OracleJSON compiles to CLOB in Oracle DDL (the dialect cannot render JSON)"""
    assert OracleJSON().compile(dialect=ORACLE_DIALECT) == "CLOB"


def test_get_table_schema_definition_memories():
    """Test getting memory table schema (USER_MEMORY_TABLE_SCHEMA)"""
    schema = get_table_schema_definition("memories")
    assert schema == USER_MEMORY_TABLE_SCHEMA
    assert "memory_id" in schema
    assert schema["memory_id"]["primary_key"] is True
    assert schema["user_id"]["index"] is True
    assert schema["created_at"]["index"] is True
    assert schema["updated_at"]["index"] is True


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
    assert schema["date"]["type"] is Date
    assert "_unique_constraints" in schema
    assert schema["_unique_constraints"] == [
        {"name": "uq_metrics_date_period", "columns": ["date", "aggregation_period"]}
    ]


def test_get_table_schema_definition_culture():
    """Test getting cultural knowledge table schema"""
    schema = get_table_schema_definition("culture")
    assert schema == CULTURAL_KNOWLEDGE_TABLE_SCHEMA
    assert schema["id"]["primary_key"] is True
    assert schema["name"]["index"] is True


def test_get_table_schema_definition_versions():
    """Test getting schema-versions table schema"""
    schema = get_table_schema_definition("versions")
    assert schema == VERSIONS_TABLE_SCHEMA
    assert schema["table_name"]["primary_key"] is True


def test_get_table_schema_definition_traces():
    """Test getting traces table schema"""
    schema = get_table_schema_definition("traces")
    assert schema == TRACE_TABLE_SCHEMA
    assert schema["trace_id"]["primary_key"] is True
    assert schema["status"]["index"] is True


def test_get_table_schema_definition_spans_default_schema():
    """Test spans schema foreign key omits schema prefix when db_schema is None (connected user)"""
    schema = get_table_schema_definition("spans", traces_table_name="agno_traces", db_schema=None)
    assert schema["span_id"]["primary_key"] is True
    assert schema["trace_id"]["foreign_key"] == "agno_traces.trace_id"


def test_get_table_schema_definition_spans_with_schema():
    """Test spans schema foreign key is schema-qualified when db_schema is set"""
    schema = get_table_schema_definition("spans", traces_table_name="agno_traces", db_schema="ai")
    assert schema["trace_id"]["foreign_key"] == "ai.agno_traces.trace_id"


def test_get_table_schema_definition_spans_custom_traces_table():
    """Test spans schema foreign key targets a custom traces table name"""
    schema = get_table_schema_definition("spans", traces_table_name="test_traces", db_schema=None)
    assert schema["trace_id"]["foreign_key"] == "test_traces.trace_id"


def test_get_table_schema_definition_invalid():
    """Test getting schema for invalid table type raises ValueError"""
    with pytest.raises(ValueError, match="Unknown table type"):
        get_table_schema_definition("invalid_table")


def test_import_guard_messages():
    """Test that oracle/oracle.py, schemas.py and utils.py guard the optional sqlalchemy
    import with a clear, actionable error message."""
    expected_message = "`sqlalchemy` not installed. Please install it using `pip install sqlalchemy`"
    for module in (oracle_module, oracle_schemas_module, oracle_utils_module):
        source = inspect.getsource(module)
        assert "try:" in source
        assert expected_message in source


# ---------------------------------------------------------------------------
# Group: utils (agno/db/oracle/utils.py)
# ---------------------------------------------------------------------------


def test_apply_sorting_no_sort_by_returns_same_statement():
    """Test apply_sorting is a no-op when sort_by is None"""
    table = _make_table()
    stmt = select(table)

    result = apply_sorting(stmt, table, sort_by=None)

    assert result is stmt


def test_apply_sorting_invalid_field_returns_same_statement():
    """Test apply_sorting ignores unknown sort fields"""
    table = _make_table()
    stmt = select(table)

    result = apply_sorting(stmt, table, sort_by="not_a_real_column")

    assert result is stmt


def test_apply_sorting_ascending():
    """Test apply_sorting applies ASC ordering when requested"""
    table = _make_table()
    stmt = select(table)

    result = apply_sorting(stmt, table, sort_by="session_id", sort_order="asc")

    assert "ORDER BY test_sessions.session_id ASC" in str(result)


def test_apply_sorting_defaults_to_descending():
    """Test apply_sorting defaults to DESC ordering when sort_order is not 'asc'"""
    table = _make_table()
    stmt = select(table)

    result = apply_sorting(stmt, table, sort_by="session_id", sort_order=None)

    assert "ORDER BY test_sessions.session_id DESC" in str(result)


def test_apply_sorting_updated_at_uses_coalesce_fallback():
    """Test apply_sorting falls back to created_at via COALESCE when sorting by updated_at,
    to correctly order pre-2.0 records with NULL updated_at."""
    columns = [
        Column("session_id", String(128), primary_key=True),
        Column("created_at", BigInteger),
        Column("updated_at", BigInteger),
    ]
    table = _make_table(columns=columns)
    stmt = select(table)

    result = apply_sorting(stmt, table, sort_by="updated_at", sort_order="asc")

    sql = str(result).lower()
    assert "coalesce(test_sessions.updated_at, test_sessions.created_at)" in sql


def test_validate_schema_exists_ok(mock_session):
    """Test validate_schema_exists does not raise when the Oracle user exists"""
    mock_session.execute.return_value.scalar.return_value = 1

    validate_schema_exists(mock_session, "ai")

    args, kwargs = mock_session.execute.call_args
    assert kwargs == {}
    assert "all_users" in str(args[0])
    assert args[1] == {"schema": "ai"}


def test_validate_schema_exists_missing_raises(mock_session):
    """Test validate_schema_exists raises a clear ValueError when the Oracle user is missing"""
    mock_session.execute.return_value.scalar.return_value = None

    with pytest.raises(ValueError, match="does not exist"):
        validate_schema_exists(mock_session, "missing_user")


def test_is_table_available_true_uses_upper_comparison(mock_session):
    """Test is_table_available compares against all_tables using UPPER() on both sides"""
    mock_session.execute.return_value.scalar.return_value = 1

    result = is_table_available(mock_session, "test_sessions", db_schema=None)

    assert result is True
    args, _ = mock_session.execute.call_args
    query_text = str(args[0])
    assert "all_tables" in query_text
    assert "UPPER(:schema)" in query_text
    assert "UPPER(:table)" in query_text
    assert args[1] == {"schema": None, "table": "test_sessions"}


def test_is_table_available_false(mock_session):
    """Test is_table_available returns False when the table is not found"""
    mock_session.execute.return_value.scalar.return_value = None

    result = is_table_available(mock_session, "test_sessions", db_schema="ai")

    assert result is False


def test_is_table_available_swallows_exceptions(mock_session):
    """Test is_table_available returns False (not raise) on query errors"""
    mock_session.execute.side_effect = Exception("connection lost")

    result = is_table_available(mock_session, "test_sessions", db_schema=None)

    assert result is False


@patch("agno.db.oracle.utils.inspect")
def test_is_valid_table_all_columns_present(mock_inspect):
    """Test is_valid_table returns True when every expected column exists"""
    expected_columns = [name for name in SESSION_TABLE_SCHEMA if not name.startswith("_")]
    mock_inspector = Mock()
    mock_inspector.get_columns.return_value = [{"name": name} for name in expected_columns]
    mock_inspect.return_value = mock_inspector

    result = is_valid_table(Mock(spec=Engine), "test_sessions", "sessions", db_schema=None)

    assert result is True
    mock_inspector.get_columns.assert_called_once_with("test_sessions", schema=None)


@patch("agno.db.oracle.utils.inspect")
def test_is_valid_table_missing_columns(mock_inspect):
    """Test is_valid_table returns False when expected columns are missing"""
    mock_inspector = Mock()
    mock_inspector.get_columns.return_value = [{"name": "session_id"}]
    mock_inspect.return_value = mock_inspector

    result = is_valid_table(Mock(spec=Engine), "test_sessions", "sessions", db_schema=None)

    assert result is False


@patch("agno.db.oracle.utils.inspect")
def test_is_valid_table_swallows_exceptions(mock_inspect):
    """Test is_valid_table returns False (not raise) on introspection errors"""
    mock_inspect.side_effect = Exception("boom")

    result = is_valid_table(Mock(spec=Engine), "test_sessions", "sessions", db_schema=None)

    assert result is False


def test_build_merge_stmt_generates_oracle_merge():
    """Test build_merge_stmt builds a MERGE INTO ... USING (... FROM dual) statement"""
    table = _make_table()

    stmt, params = build_merge_stmt(
        ORACLE_DIALECT,
        table,
        key_columns=["session_id"],
        values={"session_id": "s1", "session_type": "agent", "created_at": 1},
    )

    sql = str(stmt)
    assert sql == (
        "MERGE INTO test_sessions t USING (SELECT :session_id AS session_id, "
        ":session_type AS session_type, :created_at AS created_at FROM dual) src "
        "ON (t.session_id = src.session_id) "
        "WHEN MATCHED THEN UPDATE SET t.session_type = src.session_type, t.created_at = src.created_at "
        "WHEN NOT MATCHED THEN INSERT (session_id, session_type, created_at) "
        "VALUES (src.session_id, src.session_type, src.created_at)"
    )
    assert params == {"session_id": "s1", "session_type": "agent", "created_at": 1}


def test_build_merge_stmt_schema_qualifies_table():
    """Test build_merge_stmt schema-qualifies the target table when the table has a schema"""
    table = _make_table(schema="test_schema")

    stmt, _ = build_merge_stmt(ORACLE_DIALECT, table, key_columns=["session_id"], values={"session_id": "s1"})

    assert str(stmt).startswith("MERGE INTO test_schema.test_sessions t USING")


def test_build_merge_stmt_quotes_reserved_identifiers():
    """Test build_merge_stmt quotes Oracle reserved words like 'date'"""
    columns = [Column("id", String(128), primary_key=True), Column("date", Date)]
    table = _make_table(name="test_metrics", columns=columns)

    stmt, params = build_merge_stmt(
        ORACLE_DIALECT, table, key_columns=["id"], values={"id": "m1", "date": "2026-01-01"}
    )

    sql = str(stmt)
    assert '"date"' in sql
    assert params == {"id": "m1", "date": "2026-01-01"}


def test_build_merge_stmt_serializes_values_bound_to_json_columns():
    """Test build_merge_stmt JSON-serializes every value bound to an OracleJSON column
    (dicts, lists and plain strings alike, so string payloads round-trip through the
    column's json.loads result processor), while non-JSON columns pass through untouched."""
    columns = [
        Column("memory_id", String(128), primary_key=True),
        Column("memory", OracleJSON),
        Column("topics", OracleJSON),
        Column("summary", OracleJSON),
        Column("created_at", BigInteger),
    ]
    table = _make_table(name="test_memories", columns=columns)

    _, params = build_merge_stmt(
        ORACLE_DIALECT,
        table,
        key_columns=["memory_id"],
        values={
            "memory_id": "m1",
            "memory": "a plain string memory",
            "topics": ["a", "b"],
            "summary": {"k": "v"},
            "created_at": 1,
        },
    )

    assert params["memory"] == json.dumps("a plain string memory")
    assert params["topics"] == json.dumps(["a", "b"])
    assert params["summary"] == json.dumps({"k": "v"})
    assert params["memory_id"] == "m1"
    assert params["created_at"] == 1


def test_build_merge_stmt_keeps_none_for_json_columns():
    """Test build_merge_stmt binds None (SQL NULL) for JSON columns instead of the 'null' string"""
    columns = [
        Column("memory_id", String(128), primary_key=True),
        Column("topics", OracleJSON),
    ]
    table = _make_table(name="test_memories", columns=columns)

    _, params = build_merge_stmt(
        ORACLE_DIALECT, table, key_columns=["memory_id"], values={"memory_id": "m1", "topics": None}
    )

    assert params["topics"] is None


def test_build_merge_stmt_custom_update_columns():
    """Test build_merge_stmt only updates the columns explicitly passed as update_columns"""
    table = _make_table()

    stmt, _ = build_merge_stmt(
        ORACLE_DIALECT,
        table,
        key_columns=["session_id"],
        values={"session_id": "s1", "session_type": "agent", "created_at": 1},
        update_columns=["session_type"],
    )

    sql = str(stmt)
    assert "t.session_type = src.session_type" in sql
    assert "t.created_at = src.created_at" not in sql


def test_build_merge_stmt_matched_where_guards_update_branch():
    """Test build_merge_stmt appends matched_where to the WHEN MATCHED UPDATE branch only"""
    table = _make_table()

    stmt, params = build_merge_stmt(
        ORACLE_DIALECT,
        table,
        key_columns=["session_id"],
        values={"session_id": "s1", "session_type": "agent", "created_at": 1},
        matched_where="t.user_id = src.user_id OR t.user_id IS NULL",
    )

    sql = str(stmt)
    assert (
        "WHEN MATCHED THEN UPDATE SET t.session_type = src.session_type, t.created_at = src.created_at "
        "WHERE (t.user_id = src.user_id OR t.user_id IS NULL)" in sql
    )
    assert sql.index("WHERE (") < sql.index("WHEN NOT MATCHED")
    assert params == {"session_id": "s1", "session_type": "agent", "created_at": 1}


def test_merge_upsert_returns_affected_rowcount(mock_session):
    """Test merge_upsert surfaces the MERGE rowcount (0 = matched row skipped by the guard)"""
    table = _make_table()
    mock_session.get_bind.return_value.dialect = ORACLE_DIALECT
    mock_session.execute.return_value = Mock(rowcount=0)

    affected = merge_upsert(
        session=mock_session,
        table=table,
        key_columns=["session_id"],
        values={"session_id": "s1", "session_type": "agent"},
    )

    assert affected == 0


def test_build_merge_stmt_no_update_clause_when_all_columns_are_keys():
    """Test build_merge_stmt omits WHEN MATCHED entirely when there is nothing to update"""
    table = _make_table()

    stmt, _ = build_merge_stmt(ORACLE_DIALECT, table, key_columns=["session_id"], values={"session_id": "s1"})

    sql = str(stmt)
    assert "WHEN MATCHED" not in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql


def test_merge_upsert_generates_oracle_merge(mock_session):
    """Test merge_upsert executes a MERGE INTO ... USING (... FROM dual) statement via the session"""
    table = _make_table()
    mock_session.get_bind.return_value.dialect = ORACLE_DIALECT
    executed = {}

    def capture_execute(stmt, params=None):
        executed["sql"] = str(stmt)
        executed["params"] = params
        return Mock()

    mock_session.execute = Mock(side_effect=capture_execute)

    merge_upsert(
        session=mock_session,
        table=table,
        key_columns=["session_id"],
        values={"session_id": "s1", "session_type": "agent", "created_at": 1},
    )

    sql = executed["sql"].upper()
    assert "MERGE INTO" in sql
    assert "USING" in sql and "DUAL" in sql
    assert "WHEN MATCHED THEN UPDATE" in sql
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert executed["params"]["session_id"] == "s1"


def test_serialize_cultural_knowledge_for_db():
    """Test serialize_cultural_knowledge_for_db packs content/categories/notes into one JSON dict"""
    cultural_knowledge = CulturalKnowledge(
        id="ck1",
        name="Team norms",
        content="Always write tests",
        categories=["process"],
        notes=["note1", "note2"],
    )

    result = serialize_cultural_knowledge_for_db(cultural_knowledge)

    assert result == {
        "content": "Always write tests",
        "categories": ["process"],
        "notes": ["note1", "note2"],
    }


def test_serialize_cultural_knowledge_for_db_empty_content():
    """Test serialize_cultural_knowledge_for_db returns an empty dict when there is nothing to store"""
    cultural_knowledge = CulturalKnowledge(id="ck1", name="Empty")

    result = serialize_cultural_knowledge_for_db(cultural_knowledge)

    assert result == {}


def test_deserialize_cultural_knowledge_from_db():
    """Test deserialize_cultural_knowledge_from_db unpacks the JSON content column back into fields"""
    db_row = {
        "id": "ck1",
        "name": "Team norms",
        "summary": "summary text",
        "content": {"content": "Always write tests", "categories": ["process"], "notes": ["note1"]},
        "metadata": {"source": "onboarding"},
        "input": "raw input",
        "created_at": 1700000000,
        "updated_at": 1700000100,
        "agent_id": "agent-1",
        "team_id": "team-1",
    }

    cultural_knowledge = deserialize_cultural_knowledge_from_db(db_row)

    assert isinstance(cultural_knowledge, CulturalKnowledge)
    assert cultural_knowledge.id == "ck1"
    assert cultural_knowledge.name == "Team norms"
    assert cultural_knowledge.summary == "summary text"
    assert cultural_knowledge.content == "Always write tests"
    assert cultural_knowledge.categories == ["process"]
    assert cultural_knowledge.notes == ["note1"]
    assert cultural_knowledge.metadata == {"source": "onboarding"}
    assert cultural_knowledge.agent_id == "agent-1"
    assert cultural_knowledge.team_id == "team-1"


def test_deserialize_cultural_knowledge_from_db_missing_content():
    """Test deserialize_cultural_knowledge_from_db handles a row with no content JSON gracefully"""
    db_row = {"id": "ck2", "name": "No content"}

    cultural_knowledge = deserialize_cultural_knowledge_from_db(db_row)

    assert cultural_knowledge.content is None
    assert cultural_knowledge.categories is None
    assert cultural_knowledge.notes is None


# -- Regression tests: fixes found while exercising the provider externally --


def test_knowledge_description_is_nullable():
    """Oracle stores '' as NULL, so description cannot carry a NOT NULL constraint"""
    assert KNOWLEDGE_TABLE_SCHEMA["description"]["nullable"] is True


def test_deserialize_knowledge_row_restores_empty_description():
    """A NULL description read back from Oracle must validate as an empty string"""
    row = oracle_utils_module.deserialize_knowledge_row(
        {"id": "kr-1", "name": "Doc", "description": None, "metadata": {"a": 1}}
    )
    assert row.description == ""
    assert row.metadata == {"a": 1}

    row = oracle_utils_module.deserialize_knowledge_row({"id": "kr-2", "name": "Doc", "description": "kept"})
    assert row.description == "kept"


def test_get_or_create_table_existing_returns_cached_metadata_table(oracle_db):
    """A table already registered in the MetaData must be reused, not redefined"""
    cached_table = Table("test_sessions", oracle_db.metadata)

    with patch("agno.db.oracle.oracle.is_table_available", return_value=True):
        with patch("agno.db.oracle.oracle.is_valid_table", return_value=True):
            with patch.object(oracle_db, "_create_table") as mock_create:
                table = oracle_db._get_or_create_table(table_name="test_sessions", table_type="sessions")

    assert table is cached_table
    mock_create.assert_not_called()
