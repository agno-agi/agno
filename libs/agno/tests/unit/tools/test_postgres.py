# test_postgres_tool.py (Simplified Version)
import os
import pytest
from agno.tools.postgres import PostgresTools

# --- Test Configuration ---
DB_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "db_name": "testdb",
    "user": "testuser",
    "password": "testpassword",
    "table_schema": "company_data",
}

# --- Pytest Fixture for a Reusable Tool Instance ---
@pytest.fixture(scope="module")
def db_tools():
    """A fixture that provides a tool instance."""
    tools = PostgresTools(**DB_CONFIG)
    yield tools
    tools.close()

# --- Test Cases ---

def test_show_tables(db_tools):
    """Verify that show_tables lists all expected tables."""
    print("\n--> Testing: show_tables")
    result = db_tools.show_tables()
    assert "employees" in result
    assert "departments" in result
    print("PASSED")

def test_describe_table(db_tools):
    """Verify that describe_table returns the correct schema."""
    print("\n--> Testing: describe_table")
    result = db_tools.describe_table('employees')
    assert "column_name,data_type,is_nullable" in result
    assert "salary,numeric,YES" in result
    print("PASSED")

def test_run_query(db_tools):
    """Verify running a query returns the correct number of results."""
    print("\n--> Testing: run_query")
    result = db_tools.run_query("SELECT COUNT(*) FROM employees;")
    count = result.strip().split('\n')[-1]
    assert count == "3"
    print("PASSED")

def test_safe_export(db_tools, tmp_path):
    """Verify the safe, client-side export creates a correct file."""
    print("\n--> Testing: export_table_to_path")
    export_file = tmp_path / "employees.csv"
    result = db_tools.export_table_to_path('employees', str(export_file))
    assert "Successfully exported" in result
    assert os.path.exists(export_file)
    with open(export_file, "r") as f:
        content = f.read()
        assert "Alice" in content
        assert "Charlie" in content
    print("PASSED")

def test_inspect_query(db_tools):
    """Verify that inspect_query returns a query plan."""
    print("\n--> Testing: inspect_query")
    result = db_tools.inspect_query("SELECT name FROM employees WHERE salary > 10000;")
    assert "query plan" in result.lower()
    assert "seq scan on employees" in result.lower()
    print("PASSED")