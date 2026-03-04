from unittest.mock import Mock, mock_open, patch

import pytest

try:
    import redshift_connector
except ImportError:
    raise ImportError("`redshift_connector` not installed. Please install using `pip install redshift-connector`.")

from agno.tools.redshift import RedshiftTools

# --- Mock Data for Tests ---
MOCK_TABLES_RESULT = [("employees",), ("departments",), ("projects",)]

MOCK_DESCRIBE_RESULT = [
    ("id", "integer", "NO"),
    ("name", "character varying", "YES"),
    ("salary", "numeric", "YES"),
    ("department_id", "integer", "YES"),
]

MOCK_COUNT_RESULT = [(3,)]

MOCK_EXPORT_DATA = [
    (1, "Alice", 75000, 1),
    (2, "Bob", 80000, 2),
    (3, "Charlie", 65000, 1),
]

MOCK_EXPLAIN_RESULT = [
    ("Seq Scan on employees  (cost=0.00..35.50 rows=10 width=32)",),
    ("  Filter: (salary > 10000)",),
]


class TestRedshiftTools:
    """Unit tests for RedshiftTools using mocking."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock connection that behaves like redshift_connector connection."""
        conn = Mock()
        return conn

    @pytest.fixture
    def mock_cursor(self):
        """Create a mock cursor that behaves like redshift_connector cursor."""
        cursor = Mock()
        cursor.description = None
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = ()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.__iter__ = Mock(return_value=iter([]))
        return cursor

    @pytest.fixture
    def redshift_tools(self, mock_connection, mock_cursor):
        """Create RedshiftTools instance with mocked connection."""
        mock_connection.cursor.return_value = mock_cursor
        mock_connection.close = Mock()

        with patch("redshift_connector.connect", return_value=mock_connection):
            tools = RedshiftTools(
                host="localhost",
                port=5439,
                database="testdb",
                user="testuser",
                password="testpassword",
                table_schema="company_data",
            )
            yield tools

    def test_connection_properties(self, redshift_tools):
        """Test that connection properties are properly configured."""
        assert redshift_tools.database == "testdb"
        assert redshift_tools.host == "localhost"
        assert redshift_tools.port == 5439
        assert redshift_tools.table_schema == "company_data"

    def test_show_tables_success(self, redshift_tools, mock_connection, mock_cursor):
        """Test show_tables returns expected table list."""
        mock_cursor.description = [("table_name",)]
        mock_cursor.fetchall.return_value = MOCK_TABLES_RESULT

        result = redshift_tools.show_tables()

        mock_cursor.execute.assert_called_with(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s;", ("company_data",)
        )

        assert "table_name" in result
        assert "employees" in result
        assert "departments" in result
        assert "projects" in result

    def test_describe_table_success(self, redshift_tools, mock_connection, mock_cursor):
        """Test describe_table returns expected schema information."""
        mock_cursor.description = [("column_name",), ("data_type",), ("is_nullable",)]
        mock_cursor.fetchall.return_value = MOCK_DESCRIBE_RESULT

        result = redshift_tools.describe_table("employees")

        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args
        assert "table_schema = %s AND table_name = %s" in call_args[0][0]
        assert call_args[0][1] == ("company_data", "employees")

        assert "column_name,data_type,is_nullable" in result
        assert "salary,numeric,YES" in result

    def test_run_query_success(self, redshift_tools, mock_connection, mock_cursor):
        """Test run_query executes SQL and returns formatted results."""
        mock_cursor.description = [("count",)]
        mock_cursor.fetchall.return_value = MOCK_COUNT_RESULT

        result = redshift_tools.run_query("SELECT COUNT(*) FROM employees;")

        mock_cursor.execute.assert_called_with("SELECT COUNT(*) FROM employees;", None)

        lines = result.strip().split("\n")
        assert lines[0] == "count"
        assert lines[1] == "3"

    def test_export_table_to_path_success(self, redshift_tools, mock_connection, mock_cursor):
        """Test export_table_to_path creates CSV file safely."""
        mock_cursor.description = [("id",), ("name",), ("salary",), ("department_id",)]
        mock_cursor.__iter__ = Mock(return_value=iter(MOCK_EXPORT_DATA))

        mock_file = mock_open()
        export_path = "/tmp/test_export.csv"

        with patch("builtins.open", mock_file):
            result = redshift_tools.export_table_to_path("employees", export_path)

        mock_cursor.execute.assert_called_once()
        mock_file.assert_called_once_with(export_path, "w", newline="", encoding="utf-8")
        assert "Successfully exported table 'employees' to '/tmp/test_export.csv'" in result

    def test_inspect_query_success(self, redshift_tools, mock_connection, mock_cursor):
        """Test inspect_query returns execution plan."""
        mock_cursor.description = [("QUERY PLAN",)]
        mock_cursor.fetchall.return_value = MOCK_EXPLAIN_RESULT

        result = redshift_tools.inspect_query("SELECT name FROM employees WHERE salary > 10000;")

        mock_cursor.execute.assert_called_with("EXPLAIN SELECT name FROM employees WHERE salary > 10000;", None)

        assert "Seq Scan on employees" in result
        assert "Filter: (salary > 10000)" in result

    def test_database_error_handling(self, redshift_tools, mock_connection, mock_cursor):
        """Test proper error handling for database errors."""
        mock_cursor.execute.side_effect = redshift_connector.Error("Table does not exist")

        result = redshift_tools.show_tables()

        assert "Error executing query:" in result

    def test_export_file_error_handling(self, redshift_tools, mock_connection, mock_cursor):
        """Test error handling when file operations fail."""
        mock_cursor.description = [("id",), ("name",)]

        with patch("builtins.open", side_effect=IOError("Permission denied")):
            result = redshift_tools.export_table_to_path("employees", "/invalid/path/file.csv")

        assert "Error exporting table: Permission denied" in result

    def test_sql_injection_prevention(self, redshift_tools, mock_connection, mock_cursor):
        """Test that SQL injection attempts are safely handled."""
        mock_cursor.description = [("column_name",), ("data_type",), ("is_nullable",)]
        mock_cursor.fetchall.return_value = []

        malicious_table = "users'; DROP TABLE employees; --"
        redshift_tools.describe_table(malicious_table)

        call_args = mock_cursor.execute.call_args
        assert call_args[0][1] == ("company_data", malicious_table)
        assert "DROP TABLE" not in call_args[0][0]

    def test_iam_authentication_config(self, mock_connection, mock_cursor):
        """Test IAM authentication configuration."""
        mock_connection.cursor.return_value = mock_cursor
        mock_connection.close = Mock()
        mock_cursor.description = [("result",)]
        mock_cursor.fetchall.return_value = [(1,)]

        with patch("redshift_connector.connect", return_value=mock_connection) as mock_connect:
            tools = RedshiftTools(
                host="test-workgroup.123456.us-east-1.redshift-serverless.amazonaws.com",
                database="dev",
                iam=True,
                profile="test-profile",
                table_schema="public",
            )
            # Trigger a connection by running a query
            tools.run_query("SELECT 1")

            mock_connect.assert_called_once()
            call_kwargs = mock_connect.call_args[1]
            assert call_kwargs["iam"] is True
            assert call_kwargs["profile"] == "test-profile"
