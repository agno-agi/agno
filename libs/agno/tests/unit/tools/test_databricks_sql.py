import json
from unittest.mock import Mock, patch

from agno.tools.databricks_sql import DatabricksSQLTools


def _build_cursor(rows, description):
    cursor = Mock()
    cursor.description = description
    cursor.fetchmany.return_value = rows
    cursor.statusmessage = "OK"
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    return cursor


def _build_connection(cursor):
    connection = Mock()
    connection.closed = False
    connection.cursor.return_value = cursor
    return connection


def test_connect_normalizes_server_hostname():
    sql_module = Mock()
    sql_module.connect.return_value = Mock(closed=False)

    with patch("agno.tools.databricks_sql._get_databricks_sql_module", return_value=sql_module):
        tools = DatabricksSQLTools(
            server_hostname="https://adb-123.4.azuredatabricks.net/",
            http_path="/sql/1.0/warehouses/abc",
            access_token="dapi-test",
        )
        tools.connect()

    sql_module.connect.assert_called_once_with(
        server_hostname="adb-123.4.azuredatabricks.net",
        http_path="/sql/1.0/warehouses/abc",
        access_token="dapi-test",
    )


def test_list_catalogs_returns_json_rows():
    cursor = _build_cursor(
        rows=[("main",), ("samples",)],
        description=[("TABLE_CAT",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection)
    result = tools.list_catalogs(limit=10)

    cursor.catalogs.assert_called_once_with()
    assert json.loads(result) == [{"TABLE_CAT": "main"}, {"TABLE_CAT": "samples"}]


def test_list_schemas_uses_default_catalog():
    cursor = _build_cursor(
        rows=[("main", "default"), ("main", "analytics")],
        description=[("TABLE_CATALOG",), ("TABLE_SCHEM",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection, catalog="main")
    result = tools.list_schemas(limit=10)

    cursor.schemas.assert_called_once_with(catalog_name="main", schema_name="%")
    assert json.loads(result) == [
        {"TABLE_CATALOG": "main", "TABLE_SCHEM": "default"},
        {"TABLE_CATALOG": "main", "TABLE_SCHEM": "analytics"},
    ]


def test_list_tables_uses_catalog_and_schema():
    cursor = _build_cursor(
        rows=[("main", "analytics", "events", "TABLE")],
        description=[("TABLE_CAT",), ("TABLE_SCHEM",), ("TABLE_NAME",), ("TABLE_TYPE",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection, catalog="main", schema="analytics")
    result = tools.list_tables(limit=10)

    cursor.tables.assert_called_once_with(catalog_name="main", schema_name="analytics", table_name=None)
    assert json.loads(result) == [
        {"TABLE_CAT": "main", "TABLE_SCHEM": "analytics", "TABLE_NAME": "events", "TABLE_TYPE": "TABLE"}
    ]


def test_describe_table_returns_column_metadata():
    cursor = _build_cursor(
        rows=[("main", "analytics", "events", "event_id", "BIGINT")],
        description=[("TABLE_CAT",), ("TABLE_SCHEM",), ("TABLE_NAME",), ("COLUMN_NAME",), ("TYPE_NAME",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection, catalog="main", schema="analytics")
    result = tools.describe_table("events", limit=10)

    cursor.columns.assert_called_once_with(catalog_name="main", schema_name="analytics", table_name="events")
    assert json.loads(result) == [
        {
            "TABLE_CAT": "main",
            "TABLE_SCHEM": "analytics",
            "TABLE_NAME": "events",
            "COLUMN_NAME": "event_id",
            "TYPE_NAME": "BIGINT",
        }
    ]


def test_describe_table_falls_back_to_describe_sql_when_metadata_cursor_is_empty():
    cursor = _build_cursor(rows=[], description=[("TABLE_CAT",), ("TABLE_SCHEM",), ("TABLE_NAME",)])
    cursor.fetchmany.side_effect = [
        [],
        [("event_id", "bigint", None), ("event_ts", "timestamp", None)],
    ]

    def _execute(query):
        if query.startswith("DESCRIBE TABLE"):
            cursor.description = [("col_name",), ("data_type",), ("comment",)]

    cursor.execute.side_effect = _execute
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection, catalog="main", schema="analytics")
    result = tools.describe_table("events", limit=10)

    assert cursor.columns.call_count == 1
    cursor.execute.assert_called_once_with("DESCRIBE TABLE `main`.`analytics`.`events`")
    assert json.loads(result) == [
        {"col_name": "event_id", "data_type": "bigint", "comment": None},
        {"col_name": "event_ts", "data_type": "timestamp", "comment": None},
    ]


def test_run_sql_query_executes_read_only_query():
    cursor = _build_cursor(
        rows=[(3,)],
        description=[("row_count",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection, max_rows=50)
    result = tools.run_sql_query("SELECT COUNT(*) AS row_count FROM events", limit=10)

    cursor.execute.assert_called_once_with("SELECT COUNT(*) AS row_count FROM events")
    cursor.fetchmany.assert_called_once_with(10)
    assert json.loads(result) == [{"row_count": 3}]


def test_run_sql_query_blocks_mutating_sql():
    tools = DatabricksSQLTools(connection=Mock(closed=False))

    result = tools.run_sql_query("DELETE FROM events WHERE id = 1")

    assert "Only read-only SQL statements are allowed" in result


def test_run_sql_query_blocks_multi_statement_sql():
    tools = DatabricksSQLTools(connection=Mock(closed=False))

    result = tools.run_sql_query("SELECT 1; SELECT 2")

    assert "Only a single SQL statement is allowed" in result


def test_run_sql_query_blocks_cte_prefixed_delete():
    tools = DatabricksSQLTools(connection=Mock(closed=False))

    result = tools.run_sql_query("WITH x AS (SELECT 1) DELETE FROM events WHERE id = 1")

    assert "Only read-only SQL statements are allowed" in result


def test_run_sql_query_blocks_cte_prefixed_insert():
    tools = DatabricksSQLTools(connection=Mock(closed=False))

    result = tools.run_sql_query("WITH x AS (SELECT 1) INSERT INTO events SELECT * FROM x")

    assert "Only read-only SQL statements are allowed" in result


def test_run_sql_query_blocks_inline_comment_prefixed_mutation():
    tools = DatabricksSQLTools(connection=Mock(closed=False))

    result = tools.run_sql_query("/* comment */ WITH x AS (SELECT 1) MERGE INTO events USING x ON 1=1")

    assert "Only read-only SQL statements are allowed" in result


def test_run_sql_query_allows_cte_prefixed_select():
    cursor = _build_cursor(
        rows=[(1,)],
        description=[("ok",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection)
    result = tools.run_sql_query("WITH x AS (SELECT 1 AS ok) SELECT ok FROM x", limit=10)

    cursor.execute.assert_called_once_with("WITH x AS (SELECT 1 AS ok) SELECT ok FROM x")
    assert json.loads(result) == [{"ok": 1}]


def test_explain_sql_query_wraps_cleaned_query():
    cursor = _build_cursor(
        rows=[("== Physical Plan ==",)],
        description=[("plan",)],
    )
    connection = _build_connection(cursor)

    tools = DatabricksSQLTools(connection=connection)
    result = tools.explain_sql_query("-- explain this\nSELECT * FROM events", limit=10)

    cursor.execute.assert_called_once_with("EXPLAIN SELECT * FROM events")
    assert json.loads(result) == [{"plan": "== Physical Plan =="}]


def test_close_resets_connection():
    connection = Mock()
    connection.closed = False

    tools = DatabricksSQLTools(connection=connection)
    tools.close()

    connection.close.assert_called_once_with()
    assert tools._connection is None
