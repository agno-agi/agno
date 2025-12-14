from unittest.mock import Mock, mock_open, patch

import psycopg
import pytest

from agno.tools.postgres import PostgresTools

# --- Mock Data for Tests ---
MOCK_TABLES_RESULT = [{"table_name": "employees"}, {"table_name": "departments"}, {"table_name": "projects"}]

MOCK_DESCRIBE_RESULT = [
    {"column_name": "id", "data_type": "integer", "is_nullable": "NO"},
    {"column_name": "name", "data_type": "character varying", "is_nullable": "YES"},
    {"column_name": "salary", "data_type": "numeric", "is_nullable": "YES"},
    {"column_name": "department_id", "data_type": "integer", "is_nullable": "YES"},
]

MOCK_COUNT_RESULT = [{"count": 3}]

MOCK_EXPORT_DATA = [
    {"id": 1, "name": "Alice", "salary": 75000, "department_id": 1},
    {"id": 2, "name": "Bob", "salary": 80000, "department_id": 2},
    {"id": 3, "name": "Charlie", "salary": 65000, "department_id": 1},
]

MOCK_EXPLAIN_RESULT = [
    {"QUERY PLAN": "Seq Scan on employees  (cost=0.00..35.50 rows=10 width=32)"},
    {"QUERY PLAN": "  Filter: (salary > 10000)"},
]


@pytest.fixture
def mock_connection():
    """Create a mock connection that behaves like psycopg connection."""
    conn = Mock()
    conn.closed = False
    conn.read_only = False
    return conn


@pytest.fixture
def mock_cursor():
    """Create a mock cursor that behaves like psycopg cursor."""
    cursor = Mock()
    cursor.description = None
    cursor.fetchall.return_value = []
    cursor.fetchone.return_value = {}
    cursor.statusmessage = "Command completed successfully"
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.__iter__ = Mock(return_value=iter([]))
    return cursor


@pytest.fixture
def postgres_tools(mock_connection, mock_cursor):
    """Create PostgresTools instance with mocked connection."""
    # Setup the connection to return our mock cursor
    mock_connection.cursor.return_value = mock_cursor

    with patch("psycopg.connect", return_value=mock_connection):
        tools = PostgresTools(
            host="localhost",
            port=5433,
            db_name="testdb",
            user="testuser",
            password="testpassword",
            table_schema="company_data",
        )
        # Override the connection property to return our mock
        tools._connection = mock_connection
        yield tools


def test_connection_properties(postgres_tools, mock_connection):
    """Test that connection is properly configured."""
    # Test connection is established with correct parameters
    assert postgres_tools._connection == mock_connection
    assert postgres_tools.db_name == "testdb"
    assert postgres_tools.host == "localhost"
    assert postgres_tools.port == 5433
    assert postgres_tools.table_schema == "company_data"


def test_show_tables_success(postgres_tools, mock_connection, mock_cursor):
    """Test show_tables returns expected table list."""
    # Setup mock responses
    mock_cursor.description = [("table_name",)]
    mock_cursor.fetchall.return_value = MOCK_TABLES_RESULT

    result = postgres_tools.show_tables()

    # Verify parameterized query was used
    mock_cursor.execute.assert_called_with(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s;", ("company_data",)
    )

    # Verify result format
    assert "table_name" in result
    assert "employees" in result
    assert "departments" in result
    assert "projects" in result


def test_describe_table_success(postgres_tools, mock_connection, mock_cursor):
    """Test describe_table returns expected schema information."""
    # Setup mock responses
    mock_cursor.description = [("column_name",), ("data_type",), ("is_nullable",)]
    mock_cursor.fetchall.return_value = MOCK_DESCRIBE_RESULT

    result = postgres_tools.describe_table("employees")

    # Verify parameterized query was used (check if call contains expected parameters)
    mock_cursor.execute.assert_called()
    call_args = mock_cursor.execute.call_args
    assert "table_schema = %s AND table_name = %s" in call_args[0][0]
    assert call_args[0][1] == ("company_data", "employees")

    # Verify result format
    assert "column_name,data_type,is_nullable" in result
    assert "salary,numeric,YES" in result


def test_run_query_success(postgres_tools, mock_connection, mock_cursor):
    """Test run_query executes SQL and returns formatted results."""
    # Setup mock responses
    mock_cursor.description = [("count",)]
    mock_cursor.fetchall.return_value = MOCK_COUNT_RESULT

    result = postgres_tools.run_query("SELECT COUNT(*) FROM employees;")

    # Verify query was executed
    mock_cursor.execute.assert_called_with("SELECT COUNT(*) FROM employees;", None)

    # Verify result format
    lines = result.strip().split("\n")
    assert lines[0] == "count"  # Header
    assert lines[1] == "3"  # Data


def test_export_table_to_path_success(postgres_tools, mock_connection, mock_cursor):
    """Test export_table_to_path creates CSV file safely."""
    # Setup mock responses
    mock_cursor.description = [("id",), ("name",), ("salary",), ("department_id",)]
    # Override the __iter__ method to return our mock data
    mock_cursor.__iter__ = Mock(return_value=iter(MOCK_EXPORT_DATA))

    # Mock file operations
    mock_file = mock_open()
    export_path = "/tmp/test_export.csv"

    with patch("builtins.open", mock_file):
        result = postgres_tools.export_table_to_path("employees", export_path)

    # Verify safe query construction (using sql.Identifier)
    mock_cursor.execute.assert_called_once()

    # Verify file was opened for writing
    mock_file.assert_called_once_with(export_path, "w", newline="", encoding="utf-8")

    # Verify success message
    assert "Successfully exported table 'employees' to '/tmp/test_export.csv'" in result


def test_inspect_query_success(postgres_tools, mock_connection, mock_cursor):
    """Test inspect_query returns execution plan."""
    # Setup mock responses
    mock_cursor.description = [("QUERY PLAN",)]
    mock_cursor.fetchall.return_value = MOCK_EXPLAIN_RESULT

    result = postgres_tools.inspect_query("SELECT name FROM employees WHERE salary > 10000;")

    # Verify EXPLAIN query was executed
    mock_cursor.execute.assert_called_with("EXPLAIN SELECT name FROM employees WHERE salary > 10000;", None)

    # Verify result contains query plan
    assert "Seq Scan on employees" in result
    assert "Filter: (salary > 10000)" in result


def test_database_error_handling(postgres_tools, mock_connection, mock_cursor):
    """Test proper error handling for database errors."""
    # Setup mock to raise psycopg error
    mock_cursor.execute.side_effect = psycopg.DatabaseError("Table does not exist")
    mock_connection.rollback = Mock()

    result = postgres_tools.show_tables()

    # Verify error is caught and returned as string
    assert "Error executing query: Table does not exist" in result
    # Verify rollback was called
    mock_connection.rollback.assert_called_once()


def test_export_file_error_handling(postgres_tools, mock_connection, mock_cursor):
    """Test error handling when file operations fail."""
    # Setup mock responses
    mock_cursor.description = [("id",), ("name",)]

    # Mock file operations to raise IOError
    with patch("builtins.open", side_effect=IOError("Permission denied")):
        result = postgres_tools.export_table_to_path("employees", "/invalid/path/file.csv")

    # Verify error is caught and returned
    assert "Error exporting table: Permission denied" in result


def test_tools_has_close_method(mock_connection):
    """Test that PostgresTools has a close method for cleanup."""
    with patch("psycopg.connect", return_value=mock_connection):
        tools = PostgresTools(host="localhost", db_name="testdb")
        assert tools is not None
        assert hasattr(tools, "close")
        assert callable(tools.close)


def test_connection_recovery(mock_connection):
    """Test that connection is re-established if closed."""
    # Simulate closed connection
    mock_connection.closed = True

    with patch("psycopg.connect", return_value=mock_connection) as mock_connect:
        tools = PostgresTools(host="localhost", db_name="testdb")
        # Call connect() method to trigger connection
        tools.connect()

        # Verify connect was called
        mock_connect.assert_called()


def test_sql_injection_prevention(postgres_tools, mock_connection, mock_cursor):
    """Test that SQL injection attempts are safely handled."""
    # Setup mock
    mock_cursor.description = [("column_name",), ("data_type",), ("is_nullable",)]
    mock_cursor.fetchall.return_value = []

    # Attempt SQL injection
    malicious_table = "users'; DROP TABLE employees; --"
    postgres_tools.describe_table(malicious_table)

    # Verify the malicious input was passed as a parameter, not concatenated
    call_args = mock_cursor.execute.call_args
    assert call_args[0][1] == ("company_data", malicious_table)  # Parameters tuple
    assert "DROP TABLE" not in call_args[0][0]  # Not in the SQL string


def test_readonly_session_configuration(mock_connection):
    """Test that connection is configured as read-only."""
    with patch("psycopg.connect", return_value=mock_connection):
        tools = PostgresTools(host="localhost", db_name="testdb")
        tools.connect()  # Trigger connection establishment

        # Verify readonly session was set
        assert mock_connection.read_only is True


def test_is_connected_property(postgres_tools, mock_connection):
    """Test is_connected property returns correct state."""
    # Connection is established via fixture
    mock_connection.closed = False
    assert postgres_tools.is_connected is True

    # Simulate closed connection
    mock_connection.closed = True
    assert postgres_tools.is_connected is False

    # Simulate no connection
    postgres_tools._connection = None
    assert postgres_tools.is_connected is False


def test_close_method(mock_connection):
    """Test close method properly closes connection."""
    mock_connection.closed = False
    mock_connection.close = Mock()

    with patch("psycopg.connect", return_value=mock_connection):
        tools = PostgresTools(host="localhost", db_name="testdb")
        tools._connection = mock_connection

        tools.close()

        mock_connection.close.assert_called_once()
        assert tools._connection is None


def test_close_method_already_closed(mock_connection):
    """Test close method handles already closed connection."""
    mock_connection.closed = True
    mock_connection.close = Mock()

    with patch("psycopg.connect", return_value=mock_connection):
        tools = PostgresTools(host="localhost", db_name="testdb")
        tools._connection = mock_connection

        tools.close()

        # close() should not be called on already closed connection
        mock_connection.close.assert_not_called()


def test_ensure_connection_creates_new(mock_connection):
    """Test _ensure_connection creates connection when none exists."""
    with patch("psycopg.connect", return_value=mock_connection) as mock_connect:
        tools = PostgresTools(host="localhost", db_name="testdb")
        tools._connection = None

        result = tools._ensure_connection()

        mock_connect.assert_called()
        assert result == mock_connection


def test_ensure_connection_reuses_existing(mock_connection):
    """Test _ensure_connection reuses existing open connection."""
    mock_connection.closed = False

    with patch("psycopg.connect", return_value=mock_connection) as mock_connect:
        tools = PostgresTools(host="localhost", db_name="testdb")
        tools._connection = mock_connection
        mock_connect.reset_mock()

        result = tools._ensure_connection()

        mock_connect.assert_not_called()
        assert result == mock_connection


def test_connect_reuses_existing_connection(mock_connection):
    """Test connect() reuses existing open connection."""
    mock_connection.closed = False

    with patch("psycopg.connect", return_value=mock_connection) as mock_connect:
        tools = PostgresTools(host="localhost", db_name="testdb")
        tools._connection = mock_connection
        mock_connect.reset_mock()

        result = tools.connect()

        mock_connect.assert_not_called()
        assert result == mock_connection


def test_requires_connect_attribute():
    """Test that _requires_connect class attribute is set."""
    assert PostgresTools._requires_connect is True
