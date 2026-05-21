"""Unit tests for SnowflakeTools class."""

import json
from unittest.mock import MagicMock, patch

import pytest

from agno.tools.snowflake import SnowflakeTools


@pytest.fixture
def mock_sf_connector():
    with patch("agno.tools.snowflake.snowflake.connector") as mock_mod:
        mock_conn = MagicMock()
        mock_mod.connect.return_value = mock_conn
        mock_mod.errors.DatabaseError = Exception
        yield mock_conn


@pytest.fixture
def sf_tools(mock_sf_connector):
    tools = SnowflakeTools(
        account="test-account",
        user="test-user",
        password="test-pass",
        warehouse="TEST_WH",
        database="TEST_DB",
        schema="PUBLIC",
        all=True,
    )
    tools._conn = mock_sf_connector
    return tools


def _mock_cursor(mock_conn, description, rows):
    """Helper to set up a mock cursor with description and rows."""
    cursor = MagicMock()
    cursor.description = description
    cursor.fetchmany.return_value = rows
    mock_conn.cursor.return_value = cursor
    return cursor


# ---------------------------------------------------------------------------
# Init Tests
# ---------------------------------------------------------------------------


class TestSnowflakeInit:
    def test_init_with_credentials(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="my-account",
            user="my-user",
            password="my-pass",
        )
        assert tools.account == "my-account"
        assert tools.user == "my-user"
        assert tools.password == "my-pass"

    def test_init_with_env_variables(self, mock_sf_connector):
        with patch.dict(
            "os.environ",
            {
                "SNOWFLAKE_ACCOUNT": "env-account",
                "SNOWFLAKE_USER": "env-user",
                "SNOWFLAKE_PASSWORD": "env-pass",
                "SNOWFLAKE_WAREHOUSE": "ENV_WH",
                "SNOWFLAKE_DATABASE": "ENV_DB",
                "SNOWFLAKE_SCHEMA": "ENV_SCHEMA",
                "SNOWFLAKE_ROLE": "ENV_ROLE",
            },
        ):
            tools = SnowflakeTools()
            assert tools.account == "env-account"
            assert tools.user == "env-user"
            assert tools.warehouse == "ENV_WH"
            assert tools.database == "ENV_DB"
            assert tools.schema == "ENV_SCHEMA"
            assert tools.role == "ENV_ROLE"

    def test_init_with_key_pair(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="my-account",
            user="my-user",
            private_key_path="/path/to/key.p8",
        )
        assert tools.private_key_path == "/path/to/key.p8"
        assert tools.password is None

    @patch.dict("os.environ", {}, clear=True)
    def test_init_no_credentials_raises(self, mock_sf_connector):
        with pytest.raises(ValueError, match="credentials not configured"):
            SnowflakeTools()

    @patch.dict("os.environ", {}, clear=True)
    def test_init_no_auth_method_raises(self, mock_sf_connector):
        with pytest.raises(ValueError, match="password or private_key_path"):
            SnowflakeTools(account="acct", user="usr")

    def test_tool_registration_all(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="acct",
            user="usr",
            password="pwd",
            all=True,
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "query" in fn_names
        assert "list_databases" in fn_names
        assert "list_schemas" in fn_names
        assert "list_tables" in fn_names
        assert "describe_table" in fn_names
        assert "get_current_context" in fn_names
        assert "get_query_history" in fn_names
        assert "create_table" in fn_names
        assert "alter_table" in fn_names
        assert "drop_table" in fn_names
        assert "truncate_table" in fn_names
        assert "rename_table" in fn_names
        assert "comment_on_table" in fn_names
        assert "insert_record" in fn_names
        assert "update_records" in fn_names
        assert "delete_records" in fn_names
        assert "call_procedure" in fn_names

    def test_default_registration(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="acct",
            user="usr",
            password="pwd",
        )
        fn_names = {fn.name for fn in tools.functions.values()}
        assert "query" in fn_names
        assert "list_databases" in fn_names
        assert "list_schemas" in fn_names
        assert "list_tables" in fn_names
        assert "describe_table" in fn_names
        assert "get_current_context" in fn_names
        # Disabled by default
        assert "get_query_history" not in fn_names
        assert "create_table" not in fn_names
        assert "alter_table" not in fn_names
        assert "drop_table" not in fn_names
        assert "truncate_table" not in fn_names
        assert "rename_table" not in fn_names
        assert "comment_on_table" not in fn_names
        assert "insert_record" not in fn_names
        assert "update_records" not in fn_names
        assert "delete_records" not in fn_names
        assert "call_procedure" not in fn_names

    def test_requires_connect_flag(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="acct",
            user="usr",
            password="pwd",
        )
        assert tools.requires_connect is True


# ---------------------------------------------------------------------------
# Connection Tests
# ---------------------------------------------------------------------------


class TestConnection:
    def test_connect(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="acct",
            user="usr",
            password="pwd",
        )
        tools._conn = None
        with patch("agno.tools.snowflake.snowflake.connector") as mock_mod:
            mock_mod.connect.return_value = MagicMock()
            tools.connect()
            assert tools._conn is not None
            mock_mod.connect.assert_called_once()

    def test_connect_reuses_existing(self, sf_tools, mock_sf_connector):
        original_conn = sf_tools._conn
        sf_tools.connect()
        assert sf_tools._conn is original_conn

    def test_close(self, sf_tools, mock_sf_connector):
        sf_tools.close()
        mock_sf_connector.close.assert_called_once()
        assert sf_tools._conn is None

    def test_close_when_not_connected(self, mock_sf_connector):
        tools = SnowflakeTools(
            account="acct",
            user="usr",
            password="pwd",
        )
        tools._conn = None
        tools.close()  # Should not raise


# ---------------------------------------------------------------------------
# Query Tests
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_success(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("ID",), ("NAME",)],
            rows=[(1, "Alice"), (2, "Bob")],
        )

        result = json.loads(sf_tools.query(sql="SELECT ID, NAME FROM USERS"))
        assert result["rows"] == 2
        assert result["data"][0]["ID"] == 1
        assert result["data"][1]["NAME"] == "Bob"

    def test_query_empty_result(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("ID",)],
            rows=[],
        )

        result = json.loads(sf_tools.query(sql="SELECT ID FROM USERS WHERE 1=0"))
        assert result["rows"] == 0
        assert result["data"] == []

    def test_query_blocks_non_select(self, sf_tools):
        result = json.loads(sf_tools.query(sql="DELETE FROM USERS"))
        assert "error" in result
        assert "Only SELECT" in result["error"]

    def test_query_blocks_insert(self, sf_tools):
        result = json.loads(sf_tools.query(sql="INSERT INTO USERS VALUES (1)"))
        assert "error" in result

    def test_query_blocks_update(self, sf_tools):
        result = json.loads(sf_tools.query(sql="UPDATE USERS SET name='x'"))
        assert "error" in result

    def test_query_blocks_drop(self, sf_tools):
        result = json.loads(sf_tools.query(sql="DROP TABLE USERS"))
        assert "error" in result

    def test_query_allows_with_cte(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("ID",)],
            rows=[(1,)],
        )

        result = json.loads(sf_tools.query(sql="WITH cte AS (SELECT 1 AS id) SELECT * FROM cte"))
        assert result["rows"] == 1

    def test_query_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Connection lost")

        result = json.loads(sf_tools.query(sql="SELECT 1"))
        assert "error" in result


# ---------------------------------------------------------------------------
# Metadata Tests
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_list_databases(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("name",), ("owner",), ("created_on",)],
            rows=[("DB1", "SYSADMIN", "2024-01-01"), ("DB2", "SYSADMIN", "2024-02-01")],
        )

        result = json.loads(sf_tools.list_databases())
        assert result["total"] == 2
        assert result["databases"][0]["name"] == "DB1"

    def test_list_schemas(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("name",), ("database_name",), ("owner",)],
            rows=[("PUBLIC", "MY_DB", "SYSADMIN"), ("RAW", "MY_DB", "SYSADMIN")],
        )

        result = json.loads(sf_tools.list_schemas(database="MY_DB"))
        assert result["total"] == 2
        assert result["schemas"][0]["name"] == "PUBLIC"

    def test_list_schemas_default(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("name",), ("database_name",), ("owner",)],
            rows=[("PUBLIC", "TEST_DB", "SYSADMIN")],
        )

        result = json.loads(sf_tools.list_schemas())
        assert result["total"] == 1

    def test_list_schemas_invalid_identifier(self, sf_tools):
        result = json.loads(sf_tools.list_schemas(database="DROP TABLE; --"))
        assert "error" in result
        assert "Invalid database name" in result["error"]

    def test_list_tables(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("name",), ("database_name",), ("schema_name",), ("kind",), ("rows",)],
            rows=[
                ("CUSTOMERS", "MY_DB", "PUBLIC", "TABLE", 1000),
                ("ORDERS", "MY_DB", "PUBLIC", "TABLE", 5000),
            ],
        )

        result = json.loads(sf_tools.list_tables(database="MY_DB", schema="PUBLIC"))
        assert result["total"] == 2
        assert result["tables"][0]["name"] == "CUSTOMERS"
        assert result["tables"][1]["rows"] == 5000

    def test_list_tables_invalid_identifier(self, sf_tools):
        result = json.loads(sf_tools.list_tables(database="valid", schema="DROP TABLE; --"))
        assert "error" in result
        assert "Invalid schema name" in result["error"]

    def test_describe_table(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("name",), ("type",), ("null?",), ("default",), ("primary key",), ("comment",)],
            rows=[
                ("ID", "NUMBER(38,0)", "N", None, "Y", "Primary key"),
                ("NAME", "VARCHAR(100)", "Y", None, "N", "Customer name"),
                ("EMAIL", "VARCHAR(255)", "Y", None, "N", None),
            ],
        )

        result = json.loads(sf_tools.describe_table(table="CUSTOMERS"))
        assert result["table"] == "CUSTOMERS"
        assert len(result["columns"]) == 3
        assert result["columns"][0]["name"] == "ID"
        assert result["columns"][0]["nullable"] is False
        assert result["columns"][0]["primary_key"] is True
        assert result["columns"][1]["nullable"] is True

    def test_describe_table_invalid_identifier(self, sf_tools):
        result = json.loads(sf_tools.describe_table(table="DROP TABLE; --"))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_get_current_context(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("warehouse",), ("database",), ("schema",), ("role",), ("user",)],
            rows=[("COMPUTE_WH", "MY_DB", "PUBLIC", "ANALYST", "MY_USER")],
        )

        result = json.loads(sf_tools.get_current_context())
        assert result["warehouse"] == "COMPUTE_WH"
        assert result["database"] == "MY_DB"
        assert result["schema"] == "PUBLIC"
        assert result["role"] == "ANALYST"


# ---------------------------------------------------------------------------
# DDL and History Tests
# ---------------------------------------------------------------------------


class TestDDLMethods:
    def test_create_table_success(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[("status",)],
            rows=[("Table MY_TABLE successfully created.",)],
        )

        result = json.loads(
            sf_tools.create_table(
                table="MY_TABLE",
                columns='{"id": "INTEGER", "name": "VARCHAR(100)"}',
            )
        )
        assert result["status"] == "success"
        assert result["table"] == "MY_TABLE"
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert "CREATE TABLE MY_TABLE" in executed_sql
        assert "id INTEGER" in executed_sql
        assert "name VARCHAR(100)" in executed_sql

    def test_create_table_if_not_exists(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        sf_tools.create_table(table="T", columns='{"id": "INT"}', if_not_exists=True)
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS T" in executed_sql

    def test_create_table_invalid_table(self, sf_tools):
        result = json.loads(sf_tools.create_table(table="DROP; --", columns='{"id": "INT"}'))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_create_table_invalid_columns_json(self, sf_tools):
        result = json.loads(sf_tools.create_table(table="T", columns="not json"))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_create_table_empty_columns(self, sf_tools):
        result = json.loads(sf_tools.create_table(table="T", columns="{}"))
        assert "error" in result
        assert "non-empty" in result["error"]

    def test_create_table_invalid_column_name(self, sf_tools):
        result = json.loads(sf_tools.create_table(table="T", columns='{"id; DROP": "INT"}'))
        assert "error" in result
        assert "Invalid column name" in result["error"]

    def test_create_table_invalid_column_type(self, sf_tools):
        result = json.loads(sf_tools.create_table(table="T", columns='{"id": "INT; DROP TABLE x"}'))
        assert "error" in result
        assert "Invalid column type" in result["error"]

    def test_alter_table_add_column(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        result = json.loads(
            sf_tools.alter_table(
                table="T", operation="add_column", column="phone", column_type="VARCHAR(20)"
            )
        )
        assert result["status"] == "success"
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "ALTER TABLE T ADD COLUMN phone VARCHAR(20)"

    def test_alter_table_drop_column(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        sf_tools.alter_table(table="T", operation="drop_column", column="phone")
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "ALTER TABLE T DROP COLUMN phone"

    def test_alter_table_rename_column(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        sf_tools.alter_table(
            table="T", operation="rename_column", column="old", new_name="new"
        )
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "ALTER TABLE T RENAME COLUMN old TO new"

    def test_alter_table_invalid_operation(self, sf_tools):
        result = json.loads(sf_tools.alter_table(table="T", operation="bogus", column="c"))
        assert "error" in result
        assert "Unsupported operation" in result["error"]

    def test_alter_table_add_column_missing_type(self, sf_tools):
        result = json.loads(sf_tools.alter_table(table="T", operation="add_column", column="c"))
        assert "error" in result
        assert "Invalid column_type" in result["error"]

    def test_alter_table_rename_column_invalid_new_name(self, sf_tools):
        result = json.loads(
            sf_tools.alter_table(
                table="T", operation="rename_column", column="c", new_name="x; DROP"
            )
        )
        assert "error" in result
        assert "Invalid new_name" in result["error"]

    def test_drop_table_success(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        result = json.loads(sf_tools.drop_table(table="T"))
        assert result["status"] == "success"
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "DROP TABLE T"

    def test_drop_table_if_exists_cascade(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        sf_tools.drop_table(table="T", if_exists=True, cascade=True)
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert "IF EXISTS" in executed_sql
        assert "CASCADE" in executed_sql

    def test_drop_table_invalid(self, sf_tools):
        result = json.loads(sf_tools.drop_table(table="DROP; --"))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_truncate_table_success(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        result = json.loads(sf_tools.truncate_table(table="T"))
        assert result["status"] == "success"
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "TRUNCATE TABLE T"

    def test_truncate_table_invalid(self, sf_tools):
        result = json.loads(sf_tools.truncate_table(table="DROP; --"))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_rename_table_success(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        result = json.loads(sf_tools.rename_table(table="OLD", new_name="NEW"))
        assert result["status"] == "success"
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "ALTER TABLE OLD RENAME TO NEW"

    def test_rename_table_invalid_new_name(self, sf_tools):
        result = json.loads(sf_tools.rename_table(table="OLD", new_name="NEW; DROP"))
        assert "error" in result
        assert "Invalid new_name" in result["error"]

    def test_comment_on_table_success(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        result = json.loads(sf_tools.comment_on_table(table="T", comment="Hello"))
        assert result["status"] == "success"
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "COMMENT ON TABLE T IS 'Hello'"

    def test_comment_on_table_escapes_quotes(self, sf_tools, mock_sf_connector):
        _mock_cursor(mock_sf_connector, description=[("status",)], rows=[("ok",)])
        sf_tools.comment_on_table(table="T", comment="It's great")
        executed_sql = mock_sf_connector.cursor.return_value.execute.call_args[0][0]
        assert executed_sql == "COMMENT ON TABLE T IS 'It''s great'"

    def test_comment_on_table_invalid(self, sf_tools):
        result = json.loads(sf_tools.comment_on_table(table="DROP; --", comment="x"))
        assert "error" in result
        assert "Invalid table name" in result["error"]


class TestHistory:
    def test_get_query_history(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[
                ("query_id",),
                ("query_text",),
                ("database_name",),
                ("schema_name",),
                ("warehouse_name",),
                ("execution_status",),
                ("start_time",),
                ("total_elapsed_time",),
            ],
            rows=[
                ("abc-123", "SELECT 1", "MY_DB", "PUBLIC", "WH", "SUCCESS", "2024-01-01", 100),
            ],
        )

        result = json.loads(sf_tools.get_query_history(limit=5))
        assert result["total"] == 1
        assert result["queries"][0]["query_id"] == "abc-123"

    def test_get_query_history_limit_capped(self, sf_tools, mock_sf_connector):
        _mock_cursor(
            mock_sf_connector,
            description=[
                ("query_id",),
                ("query_text",),
                ("database_name",),
                ("schema_name",),
                ("warehouse_name",),
                ("execution_status",),
                ("start_time",),
                ("total_elapsed_time",),
            ],
            rows=[],
        )

        # Should not exceed 100 even if user passes a larger value
        sf_tools.get_query_history(limit=999)
        cursor = mock_sf_connector.cursor.return_value
        executed_sql = cursor.execute.call_args[0][0]
        assert "LIMIT 100" in executed_sql


# ---------------------------------------------------------------------------
# Identifier Validation Tests
# ---------------------------------------------------------------------------


class TestIdentifierValidation:
    def test_valid_simple_name(self):
        assert SnowflakeTools._validate_identifier("MY_TABLE") is True

    def test_valid_qualified_name(self):
        assert SnowflakeTools._validate_identifier("MY_DB.PUBLIC.MY_TABLE") is True

    def test_valid_quoted_name(self):
        assert SnowflakeTools._validate_identifier('"my table"') is True

    def test_invalid_semicolon(self):
        assert SnowflakeTools._validate_identifier("table; DROP TABLE") is False

    def test_invalid_dash_dash(self):
        assert SnowflakeTools._validate_identifier("table -- comment") is False

    def test_invalid_empty(self):
        assert SnowflakeTools._validate_identifier("") is False


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_list_databases_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Permission denied")

        result = json.loads(sf_tools.list_databases())
        assert "error" in result

    def test_describe_table_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Table not found")

        result = json.loads(sf_tools.describe_table(table="NONEXISTENT"))
        assert "error" in result

    def test_create_table_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Permission denied")

        result = json.loads(sf_tools.create_table(table="T", columns='{"id": "INT"}'))
        assert "error" in result

    def test_drop_table_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Table not found")

        result = json.loads(sf_tools.drop_table(table="T"))
        assert "error" in result

    def test_get_current_context_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Connection error")

        result = json.loads(sf_tools.get_current_context())
        assert "error" in result


# ---------------------------------------------------------------------------
# Write Operation Tests
# ---------------------------------------------------------------------------


class TestInsertRecord:
    def test_insert_success(self, sf_tools, mock_sf_connector):
        cursor = MagicMock()
        mock_sf_connector.cursor.return_value = cursor

        result = json.loads(
            sf_tools.insert_record(table="CUSTOMERS", record_data='{"NAME": "Alice", "EMAIL": "alice@test.com"}')
        )
        assert result["status"] == "success"
        assert result["table"] == "CUSTOMERS"
        assert result["rows_inserted"] == 1
        cursor.execute.assert_called_once()

    def test_insert_invalid_json(self, sf_tools):
        result = json.loads(sf_tools.insert_record(table="CUSTOMERS", record_data="not json"))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_insert_empty_data(self, sf_tools):
        result = json.loads(sf_tools.insert_record(table="CUSTOMERS", record_data="{}"))
        assert "error" in result
        assert "non-empty" in result["error"]

    def test_insert_invalid_table(self, sf_tools):
        result = json.loads(sf_tools.insert_record(table="DROP TABLE; --", record_data='{"NAME": "x"}'))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_insert_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Permission denied")

        result = json.loads(sf_tools.insert_record(table="CUSTOMERS", record_data='{"NAME": "x"}'))
        assert "error" in result


class TestUpdateRecords:
    def test_update_success(self, sf_tools, mock_sf_connector):
        cursor = MagicMock()
        cursor.rowcount = 3
        mock_sf_connector.cursor.return_value = cursor

        result = json.loads(
            sf_tools.update_records(
                table="CUSTOMERS",
                set_values='{"STATUS": "active"}',
                where_clause="REGION = 'US'",
            )
        )
        assert result["status"] == "success"
        assert result["rows_updated"] == 3

    def test_update_missing_where(self, sf_tools):
        result = json.loads(sf_tools.update_records(table="CUSTOMERS", set_values='{"STATUS": "x"}', where_clause=""))
        assert "error" in result
        assert "where_clause is required" in result["error"]

    def test_update_invalid_json(self, sf_tools):
        result = json.loads(sf_tools.update_records(table="CUSTOMERS", set_values="bad", where_clause="ID = 1"))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_update_invalid_table(self, sf_tools):
        result = json.loads(sf_tools.update_records(table="DROP; --", set_values='{"X": 1}', where_clause="ID = 1"))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_update_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Column not found")

        result = json.loads(sf_tools.update_records(table="CUSTOMERS", set_values='{"X": 1}', where_clause="ID = 1"))
        assert "error" in result


class TestDeleteRecords:
    def test_delete_success(self, sf_tools, mock_sf_connector):
        cursor = MagicMock()
        cursor.rowcount = 5
        mock_sf_connector.cursor.return_value = cursor

        result = json.loads(sf_tools.delete_records(table="CUSTOMERS", where_clause="STATUS = 'inactive'"))
        assert result["status"] == "success"
        assert result["rows_deleted"] == 5

    def test_delete_missing_where(self, sf_tools):
        result = json.loads(sf_tools.delete_records(table="CUSTOMERS", where_clause=""))
        assert "error" in result
        assert "where_clause is required" in result["error"]

    def test_delete_invalid_table(self, sf_tools):
        result = json.loads(sf_tools.delete_records(table="DROP; --", where_clause="ID = 1"))
        assert "error" in result
        assert "Invalid table name" in result["error"]

    def test_delete_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Permission denied")

        result = json.loads(sf_tools.delete_records(table="CUSTOMERS", where_clause="ID = 1"))
        assert "error" in result


class TestCallProcedure:
    def test_call_success(self, sf_tools, mock_sf_connector):
        cursor = MagicMock()
        cursor.description = [("result",)]
        cursor.fetchall.return_value = [("done",)]
        mock_sf_connector.cursor.return_value = cursor

        result = json.loads(sf_tools.call_procedure(procedure="MY_PROC", args='["arg1", 42]'))
        assert result["status"] == "success"
        assert result["result"][0]["result"] == "done"

    def test_call_no_args(self, sf_tools, mock_sf_connector):
        cursor = MagicMock()
        cursor.description = [("status",)]
        cursor.fetchall.return_value = [("ok",)]
        mock_sf_connector.cursor.return_value = cursor

        result = json.loads(sf_tools.call_procedure(procedure="MY_PROC"))
        assert result["status"] == "success"

    def test_call_invalid_args(self, sf_tools):
        result = json.loads(sf_tools.call_procedure(procedure="MY_PROC", args="not json"))
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    def test_call_args_not_array(self, sf_tools):
        result = json.loads(sf_tools.call_procedure(procedure="MY_PROC", args='{"key": "val"}'))
        assert "error" in result
        assert "JSON array" in result["error"]

    def test_call_invalid_procedure_name(self, sf_tools):
        result = json.loads(sf_tools.call_procedure(procedure="DROP; --", args="[]"))
        assert "error" in result
        assert "Invalid procedure name" in result["error"]

    def test_call_error(self, sf_tools, mock_sf_connector):
        mock_sf_connector.cursor.side_effect = Exception("Procedure not found")

        result = json.loads(sf_tools.call_procedure(procedure="NONEXISTENT"))
        assert "error" in result
