from unittest.mock import MagicMock, patch

import pytest

from agno.tools.duckdb import DuckDbTools


@pytest.fixture
def mock_duckdb_connection():
    """Mock DuckDB connection used by DuckDbTools."""
    with patch("agno.tools.duckdb.duckdb") as mock_duckdb:
        mock_connection = MagicMock()
        mock_duckdb.connect.return_value = mock_connection

        # Mock the query result
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("test_table",)]
        mock_result.columns = ["name"]
        mock_connection.sql.return_value = mock_result

        yield mock_connection


@pytest.fixture
def duckdb_tools_instance(mock_duckdb_connection):
    """Fixture to instantiate DuckDbTools with mocked connection."""
    tools = DuckDbTools()
    # Override the connection property to use the mock
    tools._connection = mock_duckdb_connection
    return tools


# --- Test Cases for Table Creation Methods ---


def test_create_table_from_path_no_quotes_around_table_name(duckdb_tools_instance, mock_duckdb_connection):
    """Test that create_table_from_path does not wrap table names in single quotes."""
    path = "/path/to/test-file.csv"
    expected_table_name = "test_file"

    result = duckdb_tools_instance.create_table_from_path(path)

    # Verify the table name returned
    assert result == expected_table_name

    # Verify the SQL statement does not contain quoted table name
    mock_duckdb_connection.sql.assert_called()
    call_args = mock_duckdb_connection.sql.call_args[0][0]
    assert f"CREATE TABLE IF NOT EXISTS {expected_table_name} AS" in call_args
    assert f"'{expected_table_name}'" not in call_args  # Should NOT contain quoted table name
    assert (
        f"read_csv('{path}', ignore_errors=false, auto_detect=true)" in call_args
    )  # CSV files should use read_csv with parameters


def test_create_table_from_path_with_replace(duckdb_tools_instance, mock_duckdb_connection):
    """Test create_table_from_path with replace=True."""
    path = "/path/to/data.json"
    expected_table_name = "data"

    result = duckdb_tools_instance.create_table_from_path(path, replace=True)

    assert result == expected_table_name
    call_args = mock_duckdb_connection.sql.call_args[0][0]
    assert f"CREATE OR REPLACE TABLE {expected_table_name} AS" in call_args
    assert f"'{expected_table_name}'" not in call_args
    assert f"SELECT * FROM '{path}'" in call_args  # Non-CSV files should use the old approach


def test_create_table_from_path_custom_table_name(duckdb_tools_instance, mock_duckdb_connection):
    """Test create_table_from_path with custom table name."""
    path = "/path/to/file.csv"
    custom_table = "my_custom_table"

    result = duckdb_tools_instance.create_table_from_path(path, table=custom_table)

    assert result == custom_table
    call_args = mock_duckdb_connection.sql.call_args[0][0]
    assert f"CREATE TABLE IF NOT EXISTS {custom_table} AS" in call_args
    assert f"'{custom_table}'" not in call_args


def test_load_local_path_to_table_no_quotes(duckdb_tools_instance, mock_duckdb_connection):
    """Test that load_local_path_to_table does not wrap table names in single quotes."""
    path = "/local/path/jira-backlog.csv"
    expected_table_name = "jira_backlog"

    table_name, sql_statement = duckdb_tools_instance.load_local_path_to_table(path)

    assert table_name == expected_table_name
    assert f"CREATE OR REPLACE TABLE {expected_table_name} AS" in sql_statement
    assert f"'{expected_table_name}'" not in sql_statement
    # The run_query method removes semicolons, so check for the statement without semicolon
    expected_call = sql_statement.rstrip(";")
    mock_duckdb_connection.sql.assert_called_with(expected_call)


def test_load_local_csv_to_table_no_quotes(duckdb_tools_instance, mock_duckdb_connection):
    """Test that load_local_csv_to_table does not wrap table names in single quotes."""
    path = "/local/path/test.data.csv"
    expected_table_name = "test_data"

    table_name, sql_statement = duckdb_tools_instance.load_local_csv_to_table(path)

    assert table_name == expected_table_name
    assert f"CREATE OR REPLACE TABLE {expected_table_name} AS" in sql_statement
    assert f"'{expected_table_name}'" not in sql_statement
    assert "read_csv(" in sql_statement
    assert "ignore_errors=false, auto_detect=true" in sql_statement


def test_load_local_csv_to_table_with_delimiter(duckdb_tools_instance, mock_duckdb_connection):
    """Test load_local_csv_to_table with custom delimiter."""
    path = "/local/path/pipe-separated.csv"
    delimiter = "|"
    expected_table_name = "pipe_separated"

    table_name, sql_statement = duckdb_tools_instance.load_local_csv_to_table(path, delimiter=delimiter)

    assert table_name == expected_table_name
    assert f"CREATE OR REPLACE TABLE {expected_table_name} AS" in sql_statement
    assert f"delim='{delimiter}'" in sql_statement
    assert f"'{expected_table_name}'" not in sql_statement


def test_load_s3_path_to_table_no_quotes(duckdb_tools_instance, mock_duckdb_connection):
    """Test that load_s3_path_to_table does not wrap table names in single quotes."""
    path = "s3://bucket/path/my-data-file.parquet"
    expected_table_name = "my_data_file"

    table_name, sql_statement = duckdb_tools_instance.load_s3_path_to_table(path)

    assert table_name == expected_table_name
    assert f"CREATE OR REPLACE TABLE {expected_table_name} AS" in sql_statement
    assert f"'{expected_table_name}'" not in sql_statement


def test_load_s3_csv_to_table_no_quotes(duckdb_tools_instance, mock_duckdb_connection):
    """Test that load_s3_csv_to_table does not wrap table names in single quotes."""
    path = "s3://bucket/data/sales-report.csv"
    expected_table_name = "sales_report"

    table_name, sql_statement = duckdb_tools_instance.load_s3_csv_to_table(path)

    assert table_name == expected_table_name
    assert f"CREATE OR REPLACE TABLE {expected_table_name} AS" in sql_statement
    assert f"'{expected_table_name}'" not in sql_statement
    assert "read_csv(" in sql_statement
    assert "ignore_errors=false, auto_detect=true" in sql_statement


# --- Test Cases for Table Name Sanitization ---


def test_get_table_name_from_path_special_characters(duckdb_tools_instance):
    """Test that table names are properly sanitized from paths with special characters."""
    test_cases = [
        ("/path/to/my-file.csv", "my_file"),
        ("/path/to/data.backup.csv", "data_backup"),
        ("/path/to/file with spaces.json", "file_with_spaces"),
        ("/path/to/complex-file.name.data.csv", "complex_file_name_data"),
        ("s3://bucket/sub/folder/test-data.parquet", "test_data"),
    ]

    for path, expected_table_name in test_cases:
        result = duckdb_tools_instance.get_table_name_from_path(path)
        assert result == expected_table_name, f"Failed for path: {path}"


# --- Test Cases for Query Execution ---


def test_run_query_success(duckdb_tools_instance, mock_duckdb_connection):
    """Test successful query execution."""
    # Setup mock result
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(1, "issue-1", "High"), (2, "issue-2", "Medium")]
    mock_result.columns = ["id", "issue_id", "priority"]
    mock_duckdb_connection.sql.return_value = mock_result

    query = "SELECT id, issue_id, priority FROM test_table"
    result = duckdb_tools_instance.run_query(query)

    expected_output = "id,issue_id,priority\n1,issue-1,High\n2,issue-2,Medium"
    assert result == expected_output
    mock_duckdb_connection.sql.assert_called_with(query)


def test_run_query_removes_backticks(duckdb_tools_instance, mock_duckdb_connection):
    """Test that run_query removes backticks from queries."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("test",)]
    mock_result.columns = ["col"]
    mock_duckdb_connection.sql.return_value = mock_result

    query_with_backticks = "SELECT `column` FROM `table`"
    expected_cleaned_query = "SELECT column FROM table"

    duckdb_tools_instance.run_query(query_with_backticks)

    mock_duckdb_connection.sql.assert_called_with(expected_cleaned_query)


def test_describe_table_success(duckdb_tools_instance, mock_duckdb_connection):
    """Test successful table description."""
    # Setup mock result for DESCRIBE query
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        ("issue_id", "VARCHAR", "YES", None, None, None),
        ("priority", "VARCHAR", "YES", None, None, None),
        ("status", "VARCHAR", "YES", None, None, None),
    ]
    mock_result.columns = ["column_name", "column_type", "null", "key", "default", "extra"]
    mock_duckdb_connection.sql.return_value = mock_result

    table_name = "test_table"
    result = duckdb_tools_instance.describe_table(table_name)

    expected_output = f"{table_name}\ncolumn_name,column_type,null,key,default,extra\nissue_id,VARCHAR,YES,None,None,None\npriority,VARCHAR,YES,None,None,None\nstatus,VARCHAR,YES,None,None,None"
    assert result == expected_output
    # The run_query method removes semicolons, so check for the statement without semicolon
    mock_duckdb_connection.sql.assert_called_with(f"DESCRIBE {table_name}")


# --- Integration Test Case ---


def test_integration_create_and_query_table(duckdb_tools_instance, mock_duckdb_connection):
    """Integration test: create table and then query it successfully."""
    # Test the workflow that was failing in the original issue
    path = "/path/to/jira_backlog.csv"
    expected_table_name = "jira_backlog"

    # Step 1: Create table
    table_name = duckdb_tools_instance.create_table_from_path(path)
    assert table_name == expected_table_name

    # Verify table creation SQL doesn't have quoted table name
    create_call_args = mock_duckdb_connection.sql.call_args[0][0]
    assert f"CREATE TABLE IF NOT EXISTS {expected_table_name} AS" in create_call_args
    assert f"'{expected_table_name}'" not in create_call_args
    assert f"read_csv('{path}', ignore_errors=false, auto_detect=true)" in create_call_args

    # Step 2: Setup mock for query execution
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [(1, "ISSUE-1", "High"), (2, "ISSUE-2", "Medium")]
    mock_result.columns = ["rownum", "issue_id", "priority"]
    mock_duckdb_connection.sql.return_value = mock_result

    # Step 3: Query the table (this was failing before the fix)
    query = f"SELECT row_number() OVER () AS rownum, issue_id, priority FROM {expected_table_name}"
    result = duckdb_tools_instance.run_query(query)

    # Verify query executed successfully
    expected_output = "rownum,issue_id,priority\n1,ISSUE-1,High\n2,ISSUE-2,Medium"
    assert result == expected_output


# --- Error Handling Tests ---


def test_run_query_duckdb_error(duckdb_tools_instance, mock_duckdb_connection):
    """Test run_query handles DuckDB errors gracefully."""
    # Create a proper DuckDB error by using the actual DuckDB module
    with patch("agno.tools.duckdb.duckdb") as mock_duckdb_module:
        # Setup the error classes to be proper exception classes
        class MockDuckDBError(Exception):
            pass

        class MockProgrammingError(Exception):
            pass

        mock_duckdb_module.Error = MockDuckDBError
        mock_duckdb_module.ProgrammingError = MockProgrammingError

        mock_duckdb_connection.sql.side_effect = MockDuckDBError("Test error")

        query = "SELECT * FROM non_existent_table"
        result = duckdb_tools_instance.run_query(query)

        assert "Test error" in result


def test_run_query_programming_error(duckdb_tools_instance, mock_duckdb_connection):
    """Test run_query handles programming errors gracefully."""
    # Create a proper DuckDB programming error
    with patch("agno.tools.duckdb.duckdb") as mock_duckdb_module:
        # Setup the error classes to be proper exception classes
        class MockDuckDBError(Exception):
            pass

        class MockProgrammingError(Exception):
            pass

        mock_duckdb_module.Error = MockDuckDBError
        mock_duckdb_module.ProgrammingError = MockProgrammingError

        mock_duckdb_connection.sql.side_effect = MockProgrammingError("Syntax error")

        query = "INVALID SQL SYNTAX"
        result = duckdb_tools_instance.run_query(query)

        assert "Syntax error" in result


# --- Test Cases for Edge Cases ---


def test_run_query_single_column_result(duckdb_tools_instance, mock_duckdb_connection):
    """Test run_query with single column results."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = [("value1",), ("value2",), ("value3",)]
    mock_result.columns = ["single_col"]
    mock_duckdb_connection.sql.return_value = mock_result

    query = "SELECT single_col FROM test_table"
    result = duckdb_tools_instance.run_query(query)

    expected_output = "single_col\nvalue1\nvalue2\nvalue3"
    assert result == expected_output


def test_run_query_no_results(duckdb_tools_instance, mock_duckdb_connection):
    """Test run_query with no results."""
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    mock_result.columns = ["col1", "col2"]
    mock_duckdb_connection.sql.return_value = mock_result

    query = "SELECT * FROM empty_table"
    result = duckdb_tools_instance.run_query(query)

    expected_output = "col1,col2\n"
    assert result == expected_output


def test_custom_table_name_with_special_chars(duckdb_tools_instance, mock_duckdb_connection):
    """Test that custom table names are used as-is without additional sanitization."""
    path = "/path/to/file.csv"
    custom_table = "my_custom_table_123"

    result = duckdb_tools_instance.create_table_from_path(path, table=custom_table)

    assert result == custom_table
    call_args = mock_duckdb_connection.sql.call_args[0][0]
    assert f"CREATE TABLE IF NOT EXISTS {custom_table} AS" in call_args
