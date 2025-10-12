"""Unit tests for SQLTools class."""

import json
import os
import tempfile

import pytest

try:
    from sqlalchemy import Column, Integer, String, create_engine
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
except ImportError:
    pytest.skip("SQLAlchemy not installed", allow_module_level=True)

from agno.tools.sql import SQLTools

# Create a test database schema
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String(50))
    email = Column(String(100))


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(100))
    price = Column(Integer)


@pytest.fixture
def test_db(request):
    """Create a temporary SQLite database for testing."""
    import gc
    
    temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_url = f"sqlite:///{temp_db.name}"
    db_file = temp_db.name
    temp_db.close()

    # Create engine and tables
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    # Add sample data
    Session = sessionmaker(bind=engine)
    session = Session()

    users = [
        User(id=1, name="Alice", email="alice@example.com"),
        User(id=2, name="Bob", email="bob@example.com"),
        User(id=3, name="Charlie", email="charlie@example.com"),
    ]
    products = [
        Product(id=1, name="Laptop", price=1200),
        Product(id=2, name="Mouse", price=25),
        Product(id=3, name="Keyboard", price=75),
    ]

    session.add_all(users)
    session.add_all(products)
    session.commit()
    session.close()
    
    # Dispose the engine to close all connections
    engine.dispose()

    # Track all engines created in tests
    engines_to_dispose = []
    
    def cleanup():
        # Dispose any engines created during the test
        for eng in engines_to_dispose:
            try:
                eng.dispose()
            except:
                pass
        
        # Force garbage collection
        gc.collect()
        
        # Try to delete file, ignore if locked
        try:
            if os.path.exists(db_file):
                os.unlink(db_file)
        except (PermissionError, OSError):
            pass
    
    request.addfinalizer(cleanup)

    yield db_url, db_file, engines_to_dispose


@pytest.fixture
def sql_tools(test_db):
    """Create SQLTools instance and ensure proper cleanup."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)
    yield tools


def test_init_with_db_url(test_db):
    """Test initialization with database URL."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    assert tools.db_engine is not None
    assert tools.read_only is False
    assert tools.max_result_rows == 1000


def test_init_with_read_only_mode(test_db):
    """Test initialization in read-only mode."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, read_only=True)
    engines_list.append(tools.db_engine)

    assert tools.read_only is True


def test_init_with_custom_settings(test_db):
    """Test initialization with custom settings."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, max_result_rows=100, query_timeout=60)
    engines_list.append(tools.db_engine)

    assert tools.max_result_rows == 100
    assert tools.query_timeout == 60


def test_list_tables(test_db):
    """Test listing tables."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.list_tables()
    tables = json.loads(result)

    # Check if it's an error response
    if isinstance(tables, dict) and "error" in tables:
        pytest.fail(f"list_tables returned error: {tables['error']}")

    assert "users" in tables
    assert "products" in tables


def test_describe_table(test_db):
    """Test describing a table."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.describe_table("users")
    schema = json.loads(result)

    # Check if it's an error response
    if isinstance(schema, dict) and "error" in schema:
        pytest.fail(f"describe_table returned error: {schema['error']}")

    assert len(schema) == 3
    column_names = [col["name"] for col in schema]
    assert "id" in column_names
    assert "name" in column_names
    assert "email" in column_names


def test_run_sql_query_basic(test_db):
    """Test running a basic SQL query."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.run_sql_query("SELECT * FROM users", limit=10)
    data = json.loads(result)

    # Check if it's an error response
    if isinstance(data, dict) and "error" in data:
        pytest.fail(f"run_sql_query returned error: {data}")

    assert len(data) == 3
    assert data[0]["name"] == "Alice"


def test_run_sql_query_with_limit(test_db):
    """Test running query with limit."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.run_sql_query("SELECT * FROM users", limit=2)
    data = json.loads(result)

    # Check if it's an error response
    if isinstance(data, dict) and "error" in data:
        pytest.fail(f"run_sql_query returned error: {data}")

    assert len(data) == 2


def test_run_sql_query_read_only_mode(test_db):
    """Test that read-only mode blocks write queries."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, read_only=True)
    engines_list.append(tools.db_engine)

    result = tools.run_sql_query("DELETE FROM users WHERE id = 1")
    response = json.loads(result)

    assert "error" in response
    assert "Read-only mode" in response["error"]


def test_run_sql_query_dangerous_delete_without_where(test_db):
    """Test that DELETE without WHERE is blocked."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, read_only=False)
    engines_list.append(tools.db_engine)

    result = tools.run_sql_query("DELETE FROM users")
    response = json.loads(result)

    assert "error" in response
    assert "WHERE clause" in response["error"]


def test_run_sql_query_dangerous_drop_table(test_db):
    """Test that DROP TABLE is blocked."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, read_only=False)
    engines_list.append(tools.db_engine)

    result = tools.run_sql_query("DROP TABLE users")
    response = json.loads(result)

    assert "error" in response
    assert "DROP" in response["error"]


def test_get_table_sample(test_db):
    """Test getting table sample."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.get_table_sample("users", limit=2)
    data = json.loads(result)

    # Check if it's an error response
    if "error" in data:
        pytest.fail(f"get_table_sample returned error: {data}")

    assert data["table"] == "users"
    assert "schema" in data
    assert "sample_rows" in data
    assert len(data["sample_rows"]) == 2
    assert data["sample_size"] == 2


def test_get_table_sample_invalid_table_name(test_db):
    """Test get_table_sample with invalid table name (SQL injection attempt)."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.get_table_sample("users; DROP TABLE users;")
    response = json.loads(result)

    assert "error" in response
    assert "Invalid table name" in response["error"]


def test_get_table_stats(test_db):
    """Test getting table statistics."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.get_table_stats("users")
    stats = json.loads(result)

    # Check if it's an error response
    if "error" in stats:
        pytest.fail(f"get_table_stats returned error: {stats}")

    assert stats["table"] == "users"
    assert stats["row_count"] == 3
    assert "indexes" in stats
    assert "primary_keys" in stats
    assert "id" in stats["primary_keys"]


def test_search_tables_exact_match(test_db):
    """Test searching tables with exact match."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.search_tables("users")
    data = json.loads(result)

    # Check if it's an error response
    if "error" in data:
        pytest.fail(f"search_tables returned error: {data}")

    assert "users" in data["matches"]
    assert data["match_count"] >= 1


def test_search_tables_with_wildcard(test_db):
    """Test searching tables with wildcard."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.search_tables("u%")
    data = json.loads(result)

    # Check if it's an error response
    if "error" in data:
        pytest.fail(f"search_tables returned error: {data}")

    assert "users" in data["matches"]


def test_search_tables_no_matches(test_db):
    """Test searching tables with no matches."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.search_tables("nonexistent")
    data = json.loads(result)

    # Check if it's an error response
    if "error" in data:
        pytest.fail(f"search_tables returned error: {data}")

    assert data["match_count"] == 0
    assert len(data["matches"]) == 0


def test_export_query_results_json(test_db):
    """Test exporting query results to JSON."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    temp_file.close()

    try:
        result = tools.export_query_results("SELECT * FROM users", format="json", filename=temp_file.name)
        response = json.loads(result)

        # Check if it's an error response
        if "error" in response:
            pytest.fail(f"export_query_results returned error: {response}")

        assert response["status"] == "success"
        assert response["rows_exported"] == 3
        assert response["format"] == "json"
        assert os.path.exists(temp_file.name)

        # Verify file contents
        with open(temp_file.name, "r") as f:
            exported_data = json.load(f)
            assert len(exported_data) == 3

    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


def test_export_query_results_csv(test_db):
    """Test exporting query results to CSV."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    temp_file.close()

    try:
        result = tools.export_query_results("SELECT * FROM users", format="csv", filename=temp_file.name)
        response = json.loads(result)

        # Check if it's an error response
        if "error" in response and response.get("error") != "Unsupported format: xml. Use 'json' or 'csv'":
            pytest.fail(f"export_query_results returned error: {response}")

        assert response["status"] == "success"
        assert response["format"] == "csv"
        assert os.path.exists(temp_file.name)

        # Verify CSV has content
        with open(temp_file.name, "r") as f:
            content = f.read()
            assert "Alice" in content
            assert "Bob" in content

    finally:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)


def test_export_query_results_invalid_format(test_db):
    """Test export with invalid format."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    result = tools.export_query_results("SELECT * FROM users", format="xml")
    response = json.loads(result)

    assert "error" in response
    assert "Unsupported format" in response["error"]


def test_validate_query_select_allowed(test_db):
    """Test that SELECT queries pass validation."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    error = tools._validate_query("SELECT * FROM users")
    assert error is None


def test_validate_query_with_clause_allowed(test_db):
    """Test that WITH queries pass validation."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    error = tools._validate_query("WITH cte AS (SELECT * FROM users) SELECT * FROM cte")
    assert error is None


def test_apply_smart_limit(test_db):
    """Test smart limit application."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    # Query without LIMIT
    query = "SELECT * FROM users"
    result = tools._apply_smart_limit(query, 10)
    assert "LIMIT 10" in result

    # Query with existing LIMIT
    query_with_limit = "SELECT * FROM users LIMIT 5"
    result = tools._apply_smart_limit(query_with_limit, 10)
    assert result == query_with_limit


def test_is_valid_identifier(test_db):
    """Test identifier validation."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    # Valid identifiers
    assert tools._is_valid_identifier("users") is True
    assert tools._is_valid_identifier("my_table") is True
    assert tools._is_valid_identifier("schema.table") is True
    assert tools._is_valid_identifier("table123") is True

    # Invalid identifiers (SQL injection attempts)
    assert tools._is_valid_identifier("users; DROP TABLE users;") is False
    assert tools._is_valid_identifier("users--") is False
    assert tools._is_valid_identifier("users/*comment*/") is False


def test_categorize_error(test_db):
    """Test error categorization."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    assert tools._categorize_error(Exception("syntax error near")) == "syntax_error"
    assert tools._categorize_error(Exception("permission denied")) == "permission_error"
    assert tools._categorize_error(Exception("table not found")) == "not_found"
    assert tools._categorize_error(Exception("connection timeout")) == "timeout"


def test_get_error_tip(test_db):
    """Test error tip generation."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    tip = tools._get_error_tip("syntax_error")
    assert "syntax" in tip.lower()

    tip = tools._get_error_tip("not_found")
    assert "list_tables" in tip


def test_toolkit_name(test_db):
    """Test that toolkit has correct name."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url)
    engines_list.append(tools.db_engine)

    assert tools.name == "sql_tools"


def test_selective_tools_enabled(test_db):
    """Test selective tool enabling."""
    db_url, _, engines_list = test_db
    tools = SQLTools(
        db_url=db_url,
        enable_list_tables=True,
        enable_describe_table=False,
        enable_run_sql_query=True,
        enable_get_table_sample=False,
    )
    engines_list.append(tools.db_engine)

    function_names = [func.name for func in tools.functions.values()]

    assert "list_tables" in function_names
    assert "describe_table" not in function_names
    assert "run_sql_query" in function_names
    assert "get_table_sample" not in function_names


def test_all_tools_enabled(test_db):
    """Test that 'all' flag enables all tools."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, all=True)
    engines_list.append(tools.db_engine)

    function_names = [func.name for func in tools.functions.values()]

    assert "list_tables" in function_names
    assert "describe_table" in function_names
    assert "run_sql_query" in function_names
    assert "get_table_sample" in function_names
    assert "get_table_stats" in function_names
    assert "search_tables" in function_names
    assert "export_query_results" in function_names


def test_max_result_rows_enforcement(test_db):
    """Test that max_result_rows is enforced."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, max_result_rows=2)
    engines_list.append(tools.db_engine)

    result = tools.run_sql_query("SELECT * FROM users", limit=None)
    data = json.loads(result)

    # Check if it's an error response
    if isinstance(data, dict) and "error" in data:
        pytest.fail(f"run_sql_query returned error: {data}")

    # Should only return 2 rows even though there are 3
    assert len(data) <= 2


def test_query_with_where_allowed(test_db):
    """Test that DELETE/UPDATE with WHERE clause are allowed when not in read-only mode."""
    db_url, _, engines_list = test_db
    tools = SQLTools(db_url=db_url, read_only=False)
    engines_list.append(tools.db_engine)

    # This should pass validation (though we won't actually execute it in this test)
    error = tools._validate_query("DELETE FROM users WHERE id = 999")
    assert error is None

    error = tools._validate_query("UPDATE users SET name = 'Test' WHERE id = 999")
    assert error is None
