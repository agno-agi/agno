# agno/tests/unit/tools/test_bigquery.py

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.google_bigquery import GoogleBigQueryTools, _clean_sql


@pytest.fixture
def mock_bq_client():
    """Mock BigQuery Client used by BQTools."""
    with patch("agno.tools.google_bigquery.bigquery.Client", autospec=True) as MockClientConstructor:
        yield MockClientConstructor.return_value


@pytest.fixture
def bq_tools_instance(mock_bq_client):  # mock_bq_client is the instance mock from the fixture above
    """Fixture to instantiate BQTools with the mocked BigQuery client."""
    tools = GoogleBigQueryTools(
        project="test-project",
        location="us-central1",
        dataset="test-dataset",
        # credentials will be None by default in BQTools, which is fine for the mocked client.
    )

    return tools


# --- Test Cases ---
def test_run_sql_query_success(bq_tools_instance, mock_bq_client):
    """Test run_sql_query successfully returns a JSON string of query results."""

    mock_result_data = [{"product_name": "Laptop", "quantity": 5}, {"product_name": "Mouse", "quantity": 20}]

    mock_query_job = MagicMock()
    mock_query_job.result.return_value = mock_result_data

    mock_bq_client.query.return_value = mock_query_job

    query = "SELECT product_name, quantity FROM sales"
    result_json_str = bq_tools_instance.run_sql_query(query)

    expected_inner_string = "[{'product_name': 'Laptop', 'quantity': 5}, {'product_name': 'Mouse', 'quantity': 20}]"
    expected_json_string = json.dumps(expected_inner_string)

    assert result_json_str == expected_json_string

    cleaned_query = _clean_sql(query)
    # Verify the call was made with cleaned query and job config
    mock_bq_client.query.assert_called_once()
    call_args = mock_bq_client.query.call_args
    assert call_args[0][0] == cleaned_query  # First positional argument should be the cleaned query
    assert len(call_args[0]) == 2  # Should have 2 positional arguments (query and job_config)


def test_list_tables_error(bq_tools_instance, mock_bq_client):
    """Test list_tables error handling."""
    mock_bq_client.list_tables.side_effect = Exception("Network Error")

    result = bq_tools_instance.list_tables()
    assert "Error getting tables: Network Error" == result


def test_describe_table_success(bq_tools_instance, mock_bq_client):
    """Test describe_table successfully returns a JSON string of table schema."""
    mock_table_api_repr = {
        "description": "Table of customer data",
        "schema": {
            "fields": [
                {"name": "customer_id", "type": "STRING"},
                {"name": "email", "type": "STRING"},
            ]
        },
    }

    mock_table_object = MagicMock()
    mock_table_object.to_api_repr.return_value = mock_table_api_repr
    mock_bq_client.get_table.return_value = mock_table_object

    result = bq_tools_instance.describe_table(table_id="customers")

    expected_data = {"table_description": "Table of customer data", "columns": "['customer_id', 'email']"}
    expected_json_string = json.dumps(expected_data)

    assert result == expected_json_string
    mock_bq_client.get_table.assert_called_once_with("test-project.test-dataset.customers")


def test_describe_table_error(bq_tools_instance, mock_bq_client):
    """Test describe_table error handling."""
    mock_bq_client.get_table.side_effect = Exception("Table Not Found")

    result = bq_tools_instance.describe_table(table_id="non_existent_table")
    assert "Error getting table schema: Table Not Found" == result


def test_run_sql_query_empty_result(bq_tools_instance, mock_bq_client):
    """Test run_sql_query with a query that returns no results."""
    mock_query_job = MagicMock()
    mock_query_job.result.return_value = []  # Empty iterable
    mock_bq_client.query.return_value = mock_query_job

    query = "SELECT * FROM empty_table"
    result = bq_tools_instance.run_sql_query(query)
    expected_json_string = json.dumps("[]")
    assert result == expected_json_string


def test_run_sql_query_error_in_client_query(bq_tools_instance, mock_bq_client):
    """Test run_sql_query when _run_sql raises an exception (e.g. client.query() fails)."""
    mock_bq_client.query.side_effect = Exception("Query Execution Failed")

    query = "SELECT * FROM some_table"
    result = bq_tools_instance.run_sql_query(query)

    expected_json_string = json.dumps("")
    assert result == expected_json_string


def test_clean_sql_preserves_token_boundaries_with_line_comments():
    """Test that _clean_sql replaces newlines with spaces to prevent line comments from swallowing queries."""
    # This was a bug: newlines were removed entirely, causing -- comments to consume the rest of the query
    sql = "SELECT * FROM table -- this is a comment\nWHERE id = 1"
    cleaned = _clean_sql(sql)
    assert cleaned == "SELECT * FROM table -- this is a comment WHERE id = 1"


def test_clean_sql_handles_escaped_newlines():
    """Test that _clean_sql handles escaped newline characters."""
    sql = "SELECT *\\nFROM table"
    cleaned = _clean_sql(sql)
    assert cleaned == "SELECT * FROM table"


def test_clean_sql_preserves_backslashes_in_string_literals():
    """Test that _clean_sql preserves backslashes (e.g., regex patterns in strings)."""
    sql = r"SELECT * FROM table WHERE regex = 'word\s+'"
    cleaned = _clean_sql(sql)
    assert cleaned == r"SELECT * FROM table WHERE regex = 'word\s+'"
