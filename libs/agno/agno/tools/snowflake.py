"""
Snowflake data warehouse tools for Agno agents.

Provides SQL query execution, schema discovery, and metadata operations
for Snowflake data warehouses.

Requirements:
    ``pip install snowflake-connector-python``

Authentication (pick one):
    **Username / Password** — set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
    SNOWFLAKE_PASSWORD, and optionally SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE,
    SNOWFLAKE_SCHEMA, SNOWFLAKE_ROLE env vars.

    **Key Pair** — set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY_PATH,
    and optionally SNOWFLAKE_PASSWORD (if the key is encrypted).
    Requires: ``pip install cryptography``
"""

import json
import re
import textwrap
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import snowflake.connector  # type: ignore[import-not-found]
except ImportError:
    raise ImportError(
        "`snowflake-connector-python` not installed. Please install using `pip install snowflake-connector-python`."
    )

# Regex to validate Snowflake identifiers (database, schema, table names)
# Allows alphanumeric, underscores, dots (for qualified names), and quoted identifiers
_VALID_IDENTIFIER = re.compile(r'^[A-Za-z0-9_.]+$|^"[^"]+"$|^[A-Za-z0-9_.]*"[^"]+"[A-Za-z0-9_.]*$')

# Regex to validate Snowflake column types (e.g. INTEGER, VARCHAR(100), NUMBER(10,2), TIMESTAMP_LTZ)
_VALID_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\s*\(\s*\d+\s*(,\s*\d+\s*)?\))?$")

_ALTER_OPS = {"add_column", "drop_column", "rename_column"}

SNOWFLAKE_INSTRUCTIONS = textwrap.dedent("""\
    You have access to Snowflake data warehouse tools for querying data and exploring schemas.

    ## Querying
    - Use the query tool to execute read-only SQL: `SELECT * FROM my_table LIMIT 10`
    - The query tool only allows SELECT statements.
    - Results are capped at max_rows to avoid overwhelming context.
    - Use LIMIT in your queries to control result size.

    ## Schema Discovery
    - Use get_current_context to see the active warehouse, database, schema, and role.
    - Use list_databases, list_schemas, list_tables to explore the warehouse structure.
    - Use describe_table to see column names, types, and nullability before writing queries.

    ## Schema Management (if enabled)
    - Use create_table to create a new table with typed columns.
    - Use alter_table to add, drop, or rename a single column (operation: add_column | drop_column | rename_column).
    - Use drop_table to remove a table.
    - Use truncate_table to delete all rows but keep the table.
    - Use rename_table to rename a table.
    - Use comment_on_table to set or update a table's comment.

    ## Write Operations (if enabled)
    - Use insert_record to add a single row to a table.
    - Use update_records to modify rows matching a WHERE condition.
    - Use delete_records to remove rows matching a WHERE condition (WHERE is required).
    - Use call_procedure to execute stored procedures.

    ## Best Practices
    - Always explore the schema before writing queries on unfamiliar tables.
    - Use fully qualified names (database.schema.table) when the context is ambiguous.
    - Use get_current_context first to understand which database/schema is active.
    - Use describe_table before insert_record or update_records to check column names and types.""")


class SnowflakeTools(Toolkit):
    _requires_connect: bool = True

    def __init__(
        self,
        account: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        warehouse: Optional[str] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        role: Optional[str] = None,
        private_key_path: Optional[str] = None,
        max_rows: int = 500,
        enable_query: bool = True,
        enable_list_databases: bool = True,
        enable_list_schemas: bool = True,
        enable_list_tables: bool = True,
        enable_describe_table: bool = True,
        enable_get_current_context: bool = True,
        enable_get_query_history: bool = False,
        enable_create_table: bool = False,
        enable_alter_table: bool = False,
        enable_drop_table: bool = False,
        enable_truncate_table: bool = False,
        enable_rename_table: bool = False,
        enable_comment_on_table: bool = False,
        enable_insert_record: bool = False,
        enable_update_records: bool = False,
        enable_delete_records: bool = False,
        enable_call_procedure: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        **kwargs,
    ):
        self.instructions = instructions if instructions else (SNOWFLAKE_INSTRUCTIONS if add_instructions else None)
        self.max_rows = max_rows

        self.account = account or getenv("SNOWFLAKE_ACCOUNT")
        self.user = user or getenv("SNOWFLAKE_USER")
        self.password = password or getenv("SNOWFLAKE_PASSWORD")
        self.warehouse = warehouse or getenv("SNOWFLAKE_WAREHOUSE")
        self.database = database or getenv("SNOWFLAKE_DATABASE")
        self.schema = schema or getenv("SNOWFLAKE_SCHEMA")
        self.role = role or getenv("SNOWFLAKE_ROLE")
        self.private_key_path = private_key_path or getenv("SNOWFLAKE_PRIVATE_KEY_PATH")

        if not self.account or not self.user:
            raise ValueError(
                "Snowflake credentials not configured. Provide at minimum:\n"
                "  - account + user + password (Username/Password auth)\n"
                "  - account + user + private_key_path (Key Pair auth)\n"
                "All values can be set via SNOWFLAKE_* environment variables."
            )

        if not self.password and not self.private_key_path:
            raise ValueError("Snowflake authentication requires either password or private_key_path.")

        self._conn: Optional[Any] = None

        tools: List[Any] = []
        if all or enable_query:
            tools.append(self.query)
        if all or enable_list_databases:
            tools.append(self.list_databases)
        if all or enable_list_schemas:
            tools.append(self.list_schemas)
        if all or enable_list_tables:
            tools.append(self.list_tables)
        if all or enable_describe_table:
            tools.append(self.describe_table)
        if all or enable_get_current_context:
            tools.append(self.get_current_context)
        if all or enable_get_query_history:
            tools.append(self.get_query_history)
        if all or enable_create_table:
            tools.append(self.create_table)
        if all or enable_alter_table:
            tools.append(self.alter_table)
        if all or enable_drop_table:
            tools.append(self.drop_table)
        if all or enable_truncate_table:
            tools.append(self.truncate_table)
        if all or enable_rename_table:
            tools.append(self.rename_table)
        if all or enable_comment_on_table:
            tools.append(self.comment_on_table)
        if all or enable_insert_record:
            tools.append(self.insert_record)
        if all or enable_update_records:
            tools.append(self.update_records)
        if all or enable_delete_records:
            tools.append(self.delete_records)
        if all or enable_call_procedure:
            tools.append(self.call_procedure)

        super().__init__(name="snowflake_tools", tools=tools, instructions=self.instructions, **kwargs)

    @staticmethod
    def _validate_identifier(name: str) -> bool:
        """Validate a Snowflake identifier to prevent SQL injection."""
        return bool(_VALID_IDENTIFIER.match(name))

    def _get_connect_kwargs(self) -> Dict[str, Any]:
        """Build connection kwargs for snowflake.connector.connect()."""
        kwargs: Dict[str, Any] = {
            "account": self.account,
            "user": self.user,
        }
        if self.private_key_path:
            try:
                from cryptography.hazmat.backends import default_backend
                from cryptography.hazmat.primitives import serialization
            except ImportError:
                raise ImportError(
                    "`cryptography` not installed. Key pair auth requires it. "
                    "Please install using `pip install cryptography`."
                )

            with open(self.private_key_path, "rb") as key_file:
                p_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=self.password.encode() if self.password else None,
                    backend=default_backend(),
                )
            kwargs["private_key"] = p_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        else:
            kwargs["password"] = self.password
        if self.warehouse:
            kwargs["warehouse"] = self.warehouse
        if self.database:
            kwargs["database"] = self.database
        if self.schema:
            kwargs["schema"] = self.schema
        if self.role:
            kwargs["role"] = self.role
        return kwargs

    def connect(self) -> None:
        """Establish the Snowflake connection."""
        if self._conn is not None:
            return
        try:
            self._conn = snowflake.connector.connect(**self._get_connect_kwargs())
        except Exception:
            logger.exception("Error connecting to Snowflake")
            raise

    def close(self) -> None:
        """Close the Snowflake connection."""
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def _execute(self, sql: str) -> List[Dict[str, Any]]:
        """Execute SQL and return results as a list of dicts."""
        if self._conn is None:
            self.connect()
        try:
            cursor = self._conn.cursor()  # type: ignore[union-attr]
            try:
                cursor.execute(sql)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchmany(self.max_rows)
                return [dict(zip(columns, row)) for row in rows]
            finally:
                cursor.close()
        except snowflake.connector.errors.DatabaseError:
            # Connection may have dropped — reconnect and retry once
            logger.warning("Snowflake connection error, reconnecting...")
            self.close()
            self.connect()
            cursor = self._conn.cursor()  # type: ignore[union-attr]
            try:
                cursor.execute(sql)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchmany(self.max_rows)
                return [dict(zip(columns, row)) for row in rows]
            finally:
                cursor.close()

    def query(self, sql: str) -> str:
        """
        Execute a read-only SQL query against Snowflake and return the results.
        Only SELECT statements are allowed.

        Args:
            sql: The SQL SELECT query string. Use LIMIT to control result size.
        """
        stripped = sql.strip().rstrip(";").strip()
        if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
            return json.dumps(
                {
                    "error": "Only SELECT and WITH (CTE) queries are allowed. "
                    "Use the dedicated DDL/DML methods (create_table, drop_table, insert_record, etc.) for other operations."
                }
            )
        try:
            results = self._execute(sql)
            return json.dumps({"rows": len(results), "data": results}, default=str)
        except Exception as e:
            logger.exception("Error executing Snowflake query")
            return json.dumps({"error": str(e)})

    def list_databases(self) -> str:
        """List all databases accessible to the current user."""
        try:
            results = self._execute("SHOW DATABASES")
            databases = [
                {
                    "name": row.get("name"),
                    "owner": row.get("owner"),
                    "created_on": row.get("created_on"),
                }
                for row in results
            ]
            return json.dumps({"total": len(databases), "databases": databases}, default=str)
        except Exception as e:
            logger.exception("Error listing Snowflake databases")
            return json.dumps({"error": str(e)})

    def list_schemas(self, database: str = "") -> str:
        """
        List schemas in a database.

        Args:
            database: Database name. If empty, uses the default database from the connection.
        """
        try:
            if database:
                if not self._validate_identifier(database):
                    return json.dumps({"error": f"Invalid database name: {database}"})
                sql = f"SHOW SCHEMAS IN DATABASE {database}"
            else:
                sql = "SHOW SCHEMAS"
            results = self._execute(sql)
            schemas = [
                {
                    "name": row.get("name"),
                    "database_name": row.get("database_name"),
                    "owner": row.get("owner"),
                }
                for row in results
            ]
            return json.dumps({"total": len(schemas), "schemas": schemas}, default=str)
        except Exception as e:
            logger.exception("Error listing Snowflake schemas")
            return json.dumps({"error": str(e)})

    def list_tables(self, database: str = "", schema: str = "") -> str:
        """
        List tables and views in a schema.

        Args:
            database: Database name. If empty, uses the default database.
            schema: Schema name. If empty, uses the default schema.
        """
        try:
            if database and not self._validate_identifier(database):
                return json.dumps({"error": f"Invalid database name: {database}"})
            if schema and not self._validate_identifier(schema):
                return json.dumps({"error": f"Invalid schema name: {schema}"})

            if database and schema:
                sql = f"SHOW TABLES IN {database}.{schema}"
            elif schema:
                sql = f"SHOW TABLES IN SCHEMA {schema}"
            else:
                sql = "SHOW TABLES"
            results = self._execute(sql)
            tables = [
                {
                    "name": row.get("name"),
                    "database_name": row.get("database_name"),
                    "schema_name": row.get("schema_name"),
                    "kind": row.get("kind"),
                    "rows": row.get("rows"),
                }
                for row in results
            ]
            return json.dumps({"total": len(tables), "tables": tables}, default=str)
        except Exception as e:
            logger.exception("Error listing Snowflake tables")
            return json.dumps({"error": str(e)})

    def describe_table(self, table: str) -> str:
        """
        Get column names, types, and nullability for a table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        try:
            results = self._execute(f"DESCRIBE TABLE {table}")
            columns = [
                {
                    "name": row.get("name"),
                    "type": row.get("type"),
                    "nullable": row.get("null?", "").upper() == "Y",
                    "default": row.get("default"),
                    "primary_key": row.get("primary key", "").upper() == "Y",
                    "comment": row.get("comment"),
                }
                for row in results
            ]
            return json.dumps({"table": table, "columns": columns}, default=str)
        except Exception as e:
            logger.exception(f"Error describing Snowflake table {table}")
            return json.dumps({"error": str(e)})

    def get_current_context(self) -> str:
        """Get the current active warehouse, database, schema, and role."""
        try:
            results = self._execute(
                "SELECT CURRENT_WAREHOUSE() AS warehouse, CURRENT_DATABASE() AS database, "
                "CURRENT_SCHEMA() AS schema, CURRENT_ROLE() AS role, CURRENT_USER() AS user"
            )
            if results:
                return json.dumps(results[0], default=str)
            return json.dumps({"error": "Could not retrieve current context."})
        except Exception as e:
            logger.exception("Error getting Snowflake context")
            return json.dumps({"error": str(e)})

    def get_query_history(self, limit: int = 20) -> str:
        """
        Get recent query history for the current user.

        Args:
            limit: Maximum number of queries to return. Default 20.
        """
        try:
            safe_limit = max(1, min(int(limit), 100))
            sql = (
                "SELECT query_id, query_text, database_name, schema_name, "
                "warehouse_name, execution_status, start_time, total_elapsed_time "
                "FROM TABLE(information_schema.query_history()) "
                f"ORDER BY start_time DESC LIMIT {safe_limit}"
            )
            results = self._execute(sql)
            return json.dumps({"total": len(results), "queries": results}, default=str)
        except Exception as e:
            logger.exception("Error getting Snowflake query history")
            return json.dumps({"error": str(e)})

    def create_table(self, table: str, columns: str, if_not_exists: bool = False) -> str:
        """
        Create a new table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            columns: JSON object mapping column names to Snowflake types.
                Example: '{"id": "INTEGER", "name": "VARCHAR(100)", "created_at": "TIMESTAMP_NTZ"}'
            if_not_exists: If True, only create the table if it does not already exist.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        try:
            cols = json.loads(columns) if isinstance(columns, str) else columns
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in columns: {e}"})

        if not isinstance(cols, dict) or not cols:
            return json.dumps({"error": "columns must be a non-empty JSON object."})

        parts: List[str] = []
        for col_name, col_type in cols.items():
            if not self._validate_identifier(col_name):
                return json.dumps({"error": f"Invalid column name: {col_name}"})
            if not isinstance(col_type, str) or not _VALID_TYPE.match(col_type.strip()):
                return json.dumps({"error": f"Invalid column type for {col_name}: {col_type}"})
            parts.append(f"{col_name} {col_type.strip()}")

        try:
            prefix = "CREATE TABLE IF NOT EXISTS" if if_not_exists else "CREATE TABLE"
            sql = f"{prefix} {table} ({', '.join(parts)})"
            results = self._execute(sql)
            return json.dumps({"status": "success", "table": table, "result": results}, default=str)
        except Exception as e:
            logger.exception(f"Error creating table {table}")
            return json.dumps({"error": str(e)})

    def alter_table(
        self,
        table: str,
        operation: str,
        column: str,
        column_type: str = "",
        new_name: str = "",
    ) -> str:
        """
        Alter a table by adding, dropping, or renaming a single column.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            operation: One of "add_column", "drop_column", or "rename_column".
            column: The column name to operate on.
            column_type: For "add_column", the Snowflake type of the new column (e.g. "VARCHAR(100)").
            new_name: For "rename_column", the new column name.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        if not self._validate_identifier(column):
            return json.dumps({"error": f"Invalid column name: {column}"})

        op = operation.lower().strip()
        if op not in _ALTER_OPS:
            return json.dumps(
                {"error": f"Unsupported operation: {operation}. Use one of: {sorted(_ALTER_OPS)}"}
            )

        if op == "add_column":
            if not column_type or not _VALID_TYPE.match(column_type.strip()):
                return json.dumps({"error": f"Invalid column_type for add_column: {column_type}"})
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type.strip()}"
        elif op == "drop_column":
            sql = f"ALTER TABLE {table} DROP COLUMN {column}"
        else:  # rename_column
            if not self._validate_identifier(new_name):
                return json.dumps({"error": f"Invalid new_name: {new_name}"})
            sql = f"ALTER TABLE {table} RENAME COLUMN {column} TO {new_name}"

        try:
            results = self._execute(sql)
            return json.dumps(
                {"status": "success", "table": table, "operation": op, "result": results}, default=str
            )
        except Exception as e:
            logger.exception(f"Error altering table {table}")
            return json.dumps({"error": str(e)})

    def drop_table(self, table: str, if_exists: bool = False, cascade: bool = False) -> str:
        """
        Drop a table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            if_exists: If True, do not error if the table does not exist.
            cascade: If True, also drop dependent views (CASCADE). Default behavior is RESTRICT.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        try:
            prefix = "DROP TABLE IF EXISTS" if if_exists else "DROP TABLE"
            suffix = " CASCADE" if cascade else ""
            sql = f"{prefix} {table}{suffix}"
            results = self._execute(sql)
            return json.dumps({"status": "success", "table": table, "result": results}, default=str)
        except Exception as e:
            logger.exception(f"Error dropping table {table}")
            return json.dumps({"error": str(e)})

    def truncate_table(self, table: str) -> str:
        """
        Remove all rows from a table while keeping its structure.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        try:
            results = self._execute(f"TRUNCATE TABLE {table}")
            return json.dumps({"status": "success", "table": table, "result": results}, default=str)
        except Exception as e:
            logger.exception(f"Error truncating table {table}")
            return json.dumps({"error": str(e)})

    def rename_table(self, table: str, new_name: str) -> str:
        """
        Rename a table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            new_name: The new table name.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        if not self._validate_identifier(new_name):
            return json.dumps({"error": f"Invalid new_name: {new_name}"})
        try:
            results = self._execute(f"ALTER TABLE {table} RENAME TO {new_name}")
            return json.dumps(
                {"status": "success", "table": table, "new_name": new_name, "result": results},
                default=str,
            )
        except Exception as e:
            logger.exception(f"Error renaming table {table}")
            return json.dumps({"error": str(e)})

    def comment_on_table(self, table: str, comment: str) -> str:
        """
        Set or update the comment on a table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            comment: The comment text. Single quotes are escaped automatically.
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        try:
            escaped = comment.replace("'", "''")
            results = self._execute(f"COMMENT ON TABLE {table} IS '{escaped}'")
            return json.dumps({"status": "success", "table": table, "result": results}, default=str)
        except Exception as e:
            logger.exception(f"Error commenting on table {table}")
            return json.dumps({"error": str(e)})

    def insert_record(self, table: str, record_data: str) -> str:
        """
        Insert a single record into a Snowflake table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            record_data: JSON string of column name-value pairs.
                Example: '{"NAME": "Alice", "EMAIL": "alice@example.com"}'
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        try:
            data = json.loads(record_data) if isinstance(record_data, str) else record_data
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in record_data: {e}"})

        if not isinstance(data, dict) or not data:
            return json.dumps({"error": "record_data must be a non-empty JSON object."})

        try:
            columns = ", ".join(data.keys())
            placeholders = ", ".join(["%s"] * len(data))
            sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"

            if self._conn is None:
                self.connect()
            cursor = self._conn.cursor()  # type: ignore[union-attr]
            try:
                cursor.execute(sql, list(data.values()))
                return json.dumps({"status": "success", "table": table, "rows_inserted": 1}, default=str)
            finally:
                cursor.close()
        except Exception as e:
            logger.exception(f"Error inserting record into {table}")
            return json.dumps({"error": str(e)})

    def update_records(self, table: str, set_values: str, where_clause: str) -> str:
        """
        Update records in a Snowflake table.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            set_values: JSON string of column name-value pairs to update.
                Example: '{"STATUS": "active", "UPDATED_AT": "2024-01-01"}'
            where_clause: SQL WHERE condition (without the WHERE keyword).
                Example: 'ID = 123' or 'STATUS = ''inactive'' AND CREATED_AT < ''2024-01-01'''
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        if not where_clause or not where_clause.strip():
            return json.dumps({"error": "where_clause is required to prevent accidental full-table updates."})

        try:
            data = json.loads(set_values) if isinstance(set_values, str) else set_values
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in set_values: {e}"})

        if not isinstance(data, dict) or not data:
            return json.dumps({"error": "set_values must be a non-empty JSON object."})

        try:
            set_parts = ", ".join([f"{col} = %s" for col in data.keys()])
            sql = f"UPDATE {table} SET {set_parts} WHERE {where_clause}"

            if self._conn is None:
                self.connect()
            cursor = self._conn.cursor()  # type: ignore[union-attr]
            try:
                cursor.execute(sql, list(data.values()))
                rows_updated = cursor.rowcount
                return json.dumps({"status": "success", "table": table, "rows_updated": rows_updated}, default=str)
            finally:
                cursor.close()
        except Exception as e:
            logger.exception(f"Error updating records in {table}")
            return json.dumps({"error": str(e)})

    def delete_records(self, table: str, where_clause: str) -> str:
        """
        Delete records from a Snowflake table. A WHERE clause is required.

        Args:
            table: Fully qualified table name (e.g. MY_DB.PUBLIC.MY_TABLE) or just the table name.
            where_clause: SQL WHERE condition (without the WHERE keyword).
                Example: 'ID = 123' or 'STATUS = ''inactive'''
        """
        if not self._validate_identifier(table):
            return json.dumps({"error": f"Invalid table name: {table}"})
        if not where_clause or not where_clause.strip():
            return json.dumps({"error": "where_clause is required to prevent accidental full-table deletes."})

        try:
            sql = f"DELETE FROM {table} WHERE {where_clause}"

            if self._conn is None:
                self.connect()
            cursor = self._conn.cursor()  # type: ignore[union-attr]
            try:
                cursor.execute(sql)
                rows_deleted = cursor.rowcount
                return json.dumps({"status": "success", "table": table, "rows_deleted": rows_deleted}, default=str)
            finally:
                cursor.close()
        except Exception as e:
            logger.exception(f"Error deleting records from {table}")
            return json.dumps({"error": str(e)})

    def call_procedure(self, procedure: str, args: str = "[]") -> str:
        """
        Call a Snowflake stored procedure.

        Args:
            procedure: Fully qualified procedure name (e.g. MY_DB.PUBLIC.MY_PROC) or just the name.
            args: JSON array of arguments to pass to the procedure.
                Example: '["arg1", 42, true]'
        """
        if not self._validate_identifier(procedure):
            return json.dumps({"error": f"Invalid procedure name: {procedure}"})
        try:
            parsed_args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError as e:
            return json.dumps({"error": f"Invalid JSON in args: {e}"})

        if not isinstance(parsed_args, list):
            return json.dumps({"error": "args must be a JSON array."})

        try:
            placeholders = ", ".join(["%s"] * len(parsed_args)) if parsed_args else ""
            sql = f"CALL {procedure}({placeholders})"

            if self._conn is None:
                self.connect()
            cursor = self._conn.cursor()  # type: ignore[union-attr]
            try:
                cursor.execute(sql, parsed_args if parsed_args else None)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                results = [dict(zip(columns, row)) for row in rows]
                return json.dumps({"status": "success", "result": results}, default=str)
            finally:
                cursor.close()
        except Exception as e:
            logger.exception(f"Error calling procedure {procedure}")
            return json.dumps({"error": str(e)})
