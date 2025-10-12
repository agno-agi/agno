import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

try:
    from sqlalchemy import Engine, create_engine, event
    from sqlalchemy.inspection import inspect
    from sqlalchemy.orm import Session, sessionmaker
    from sqlalchemy.pool import NullPool
    from sqlalchemy.sql.expression import text
except ImportError:
    raise ImportError("`sqlalchemy` not installed")


class SQLTools(Toolkit):
    def __init__(
        self,
        db_url: Optional[str] = None,
        db_engine: Optional[Engine] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
        tables: Optional[Dict[str, Any]] = None,
        read_only: bool = False,
        query_timeout: Optional[int] = 30,
        max_result_rows: int = 1000,
        dangerous_keywords: Optional[Set[str]] = None,
        enable_list_tables: bool = True,
        enable_describe_table: bool = True,
        enable_run_sql_query: bool = True,
        enable_get_table_sample: bool = True,
        enable_get_table_stats: bool = True,
        enable_search_tables: bool = True,
        enable_export_query_results: bool = True,
        all: bool = False,
        **kwargs,
    ):
        # Get the database engine
        _engine: Optional[Engine] = db_engine
        if _engine is None and db_url is not None:
            # If sqlite, avoid connection pooling and set check_same_thread so short-lived connections don't lock file
            if db_url.startswith("sqlite://") or db_url.startswith("sqlite:"):
                _engine = create_engine(
                    db_url,
                    connect_args={"check_same_thread": False},
                    poolclass=NullPool,
                )
            else:
                _engine = create_engine(db_url)
        elif user and password and host and port and dialect:
            if dialect is not None and dialect.lower().startswith("sqlite"):
                # unlikely with user/pw, but handle defensively
                _engine = create_engine(
                    f"{dialect}://{user}:{password}@{host}:{port}/{schema}"
                    if schema
                    else f"{dialect}://{user}:{password}@{host}:{port}",
                    connect_args={"check_same_thread": False},
                    poolclass=NullPool,
                )
            else:
                if schema is not None:
                    _engine = create_engine(f"{dialect}://{user}:{password}@{host}:{port}/{schema}")
                else:
                    _engine = create_engine(f"{dialect}://{user}:{password}@{host}:{port}")

        if _engine is None:
            raise ValueError("Could not build the database connection")

        # Database connection
        self.db_engine: Engine = _engine
        self.Session: sessionmaker[Session] = sessionmaker(bind=self.db_engine)

        # Security and performance settings
        self.read_only: bool = read_only
        self.query_timeout: Optional[int] = query_timeout
        self.max_result_rows: int = max_result_rows
        self.dangerous_keywords: Set[str] = dangerous_keywords or {
            "DROP",
            "DELETE",
            "TRUNCATE",
            "ALTER",
            "CREATE",
            "GRANT",
            "REVOKE",
            "INSERT",
            "UPDATE",
        }

        # Set query timeout if specified (only for databases that support it)
        if self.query_timeout is not None and dialect and dialect.lower() in ["postgresql", "postgres"]:
            timeout_ms = self.query_timeout * 1000

            @event.listens_for(_engine, "before_cursor_execute")
            def receive_before_cursor_execute(conn, cursor, statement, params, context, executemany):
                try:
                    conn.connection.connection.execute(f"SET statement_timeout = {timeout_ms}")
                except Exception as e:
                    log_debug(f"Could not set query timeout: {e}")

        self.schema = schema

        # Tables this toolkit can access
        self.tables: Optional[Dict[str, Any]] = tables

        tools: List[Any] = []
        if enable_list_tables or all:
            tools.append(self.list_tables)
        if enable_describe_table or all:
            tools.append(self.describe_table)
        if enable_run_sql_query or all:
            tools.append(self.run_sql_query)
        if enable_get_table_sample or all:
            tools.append(self.get_table_sample)
        if enable_get_table_stats or all:
            tools.append(self.get_table_stats)
        if enable_search_tables or all:
            tools.append(self.search_tables)
        if enable_export_query_results or all:
            tools.append(self.export_query_results)

        super().__init__(name="sql_tools", tools=tools, **kwargs)

    def list_tables(self) -> str:
        """Use this function to get a list of table names in the database.

        Returns:
            str: list of tables in the database.
        """
        if self.tables is not None:
            return json.dumps(self.tables)

        try:
            log_debug("listing tables in the database")
            inspector = inspect(self.db_engine)
            if self.schema:
                table_names = inspector.get_table_names(schema=self.schema)
            else:
                table_names = inspector.get_table_names()
            log_debug(f"table_names: {table_names}")
            return json.dumps(table_names)
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return json.dumps({"error": f"Error getting tables: {e}"})

    def describe_table(self, table_name: str) -> str:
        """Use this function to describe a table.

        Args:
            table_name (str): The name of the table to get the schema for.

        Returns:
            str: schema of a table
        """

        try:
            log_debug(f"Describing table: {table_name}")
            inspector = inspect(self.db_engine)
            table_schema = inspector.get_columns(table_name, schema=self.schema)
            return json.dumps(
                [
                    {"name": column["name"], "type": str(column["type"]), "nullable": column["nullable"]}
                    for column in table_schema
                ]
            )
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            return json.dumps({"error": f"Error getting table schema: {e}"})

    def run_sql_query(self, query: str, limit: Optional[int] = 10) -> str:
        """Use this function to run a SQL query and return the result.

        Args:
            query (str): The query to run.
            limit (int, optional): The number of rows to return. Defaults to 10. Use `None` to show all results.
        Returns:
            str: Result of the SQL query.
        Notes:
            - The result may be empty if the query does not return any data.
            - In read-only mode, only SELECT queries are allowed.
        """

        try:
            # Validate query for safety
            validation_error = self._validate_query(query)
            if validation_error:
                return json.dumps({"error": validation_error, "tip": "Check query for dangerous operations"})

            # Apply smart limit if not present in query
            formatted_query = self._apply_smart_limit(query, limit)

            return json.dumps(self.run_sql(sql=formatted_query, limit=limit), default=str)
        except Exception as e:
            logger.error(f"Error running query: {e}")
            error_type = self._categorize_error(e)
            return json.dumps(
                {
                    "error": str(e),
                    "error_type": error_type,
                    "tip": self._get_error_tip(error_type),
                }
            )

    def run_sql(self, sql: str, limit: Optional[int] = None) -> List[dict]:
        """Internal function to run a sql query.

        Args:
            sql (str): The sql query to run.
            limit (int, optional): The number of rows to return. Defaults to None.

        Returns:
            List[dict]: The result of the query.
        """
        log_debug(f"Running sql |\n{sql}")

        with self.Session() as sess, sess.begin():
            result = sess.execute(text(sql))

            # Check if the operation has returned rows.
            try:
                # Respect max_result_rows limit
                effective_limit = limit
                if effective_limit is None or effective_limit > self.max_result_rows:
                    effective_limit = self.max_result_rows

                if effective_limit:
                    rows = result.fetchmany(effective_limit)
                else:
                    rows = result.fetchall()
                return [row._asdict() for row in rows]
            except Exception as e:
                logger.error(f"Error while executing SQL: {e}")
                return []

    def get_table_sample(self, table_name: str, limit: int = 5) -> str:
        """Get sample rows from a table to understand its data.

        Args:
            table_name (str): The name of the table to sample.
            limit (int, optional): Number of sample rows to return. Defaults to 5.

        Returns:
            str: JSON with table schema and sample data.
        """
        try:
            log_info(f"Getting sample data from table: {table_name}")

            # Validate table name to prevent SQL injection
            if not self._is_valid_identifier(table_name):
                return json.dumps({"error": "Invalid table name", "tip": "Table name contains invalid characters"})

            # Get schema
            inspector = inspect(self.db_engine)
            columns = inspector.get_columns(table_name, schema=self.schema)
            schema_info = [
                {"name": col["name"], "type": str(col["type"]), "nullable": col["nullable"]} for col in columns
            ]

            # Get sample data
            query = f"SELECT * FROM {table_name} LIMIT {limit}"
            sample_data = self.run_sql(sql=query, limit=limit)

            return json.dumps(
                {
                    "table": table_name,
                    "schema": schema_info,
                    "sample_rows": sample_data,
                    "sample_size": len(sample_data),
                },
                default=str,
            )
        except Exception as e:
            logger.error(f"Error getting table sample: {e}")
            return json.dumps({"error": str(e), "tip": "Check if table exists and you have permission"})

    def get_table_stats(self, table_name: str) -> str:
        """Get statistics about a table (row count, size, indexes).

        Args:
            table_name (str): The name of the table.

        Returns:
            str: JSON with table statistics.
        """
        try:
            log_info(f"Getting statistics for table: {table_name}")

            if not self._is_valid_identifier(table_name):
                return json.dumps({"error": "Invalid table name"})

            inspector = inspect(self.db_engine)

            # Get row count
            count_query = f"SELECT COUNT(*) as row_count FROM {table_name}"
            count_result = self.run_sql(sql=count_query, limit=1)
            row_count = count_result[0]["row_count"] if count_result else 0

            # Get indexes
            indexes = inspector.get_indexes(table_name, schema=self.schema)
            index_info = [
                {"name": idx["name"], "columns": idx["column_names"], "unique": idx["unique"]} for idx in indexes
            ]

            # Get primary keys
            pk = inspector.get_pk_constraint(table_name, schema=self.schema)
            primary_keys = pk.get("constrained_columns", [])

            # Get foreign keys
            fks = inspector.get_foreign_keys(table_name, schema=self.schema)
            foreign_keys = [
                {
                    "constrained_columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"],
                }
                for fk in fks
            ]

            return json.dumps(
                {
                    "table": table_name,
                    "row_count": row_count,
                    "indexes": index_info,
                    "primary_keys": primary_keys,
                    "foreign_keys": foreign_keys,
                },
                default=str,
            )
        except Exception as e:
            logger.error(f"Error getting table stats: {e}")
            return json.dumps({"error": str(e)})

    def search_tables(self, pattern: str) -> str:
        """Search for tables matching a pattern.

        Args:
            pattern (str): Pattern to match table names (case-insensitive, supports % as wildcard).

        Returns:
            str: JSON list of matching table names.
        """
        try:
            log_info(f"Searching tables with pattern: {pattern}")

            inspector = inspect(self.db_engine)
            if self.schema:
                all_tables = inspector.get_table_names(schema=self.schema)
            else:
                all_tables = inspector.get_table_names()

            # Convert SQL pattern to regex (% becomes .*)
            regex_pattern = pattern.replace("%", ".*").lower()
            matching_tables = [table for table in all_tables if re.match(regex_pattern, table.lower())]

            return json.dumps(
                {"pattern": pattern, "matches": matching_tables, "match_count": len(matching_tables)}, default=str
            )
        except Exception as e:
            logger.error(f"Error searching tables: {e}")
            return json.dumps({"error": str(e)})

    def export_query_results(self, query: str, format: str = "json", filename: Optional[str] = None) -> str:
        """Export query results to a file.

        Args:
            query (str): SQL query to execute.
            format (str, optional): Output format - 'json' or 'csv'. Defaults to 'json'.
            filename (str, optional): Output filename. Auto-generated if not provided.

        Returns:
            str: JSON with export status and filename.
        """
        try:
            log_info(f"Exporting query results to {format}")

            # Validate query
            validation_error = self._validate_query(query)
            if validation_error:
                return json.dumps({"error": validation_error})

            # Execute query
            results = self.run_sql(sql=query, limit=self.max_result_rows)

            if not results:
                return json.dumps({"error": "Query returned no results"})

            # Generate filename if not provided
            if filename is None:
                import datetime

                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"query_results_{timestamp}.{format}"

            # Ensure filename is a Path
            filename_path = Path(filename)

            # If parent directory doesn't exist, try to create it (safe no-op for same-dir)
            if filename_path.parent and not filename_path.parent.exists():
                try:
                    filename_path.parent.mkdir(parents=True, exist_ok=True)
                except Exception:
                    # ignore parent creation errors; we'll hit open() error below if necessary
                    pass

            # Export based on format
            try:
                if format == "json":
                    with filename_path.open("w", encoding="utf-8") as f:
                        json.dump(results, f, indent=2, default=str)
                elif format == "csv":
                    import csv

                    with filename_path.open("w", newline="", encoding="utf-8") as f:
                        if results:
                            writer = csv.DictWriter(f, fieldnames=results[0].keys())
                            writer.writeheader()
                            writer.writerows(results)
                else:
                    return json.dumps({"error": f"Unsupported format: {format}. Use 'json' or 'csv'"})
            except PermissionError as e:
                logger.error(f"PermissionError exporting results: {e}")
                return json.dumps(
                    {
                        "error": str(e),
                        "tip": "PermissionError: the file is open in another process. Close editors/DB tools (or use a different filename/path).",
                    }
                )

            return json.dumps(
                {
                    "status": "success",
                    "filename": str(filename_path),
                    "rows_exported": len(results),
                    "format": format,
                }
            )
        except Exception as e:
            logger.error(f"Error exporting query results: {e}")
            return json.dumps({"error": str(e)})

    # Helper methods for validation and error handling

    def _validate_query(self, query: str) -> Optional[str]:
        """Validate query for safety and read-only mode.

        Args:
            query (str): SQL query to validate.

        Returns:
            Optional[str]: Error message if invalid, None if valid.
        """
        query_upper = query.upper().strip()

        # Check read-only mode
        if self.read_only:
            if not query_upper.startswith("SELECT") and not query_upper.startswith("WITH"):
                return "Read-only mode: Only SELECT and WITH queries are allowed"

        # Check for dangerous operations
        for keyword in self.dangerous_keywords:
            if re.search(rf"\b{keyword}\b", query_upper):
                # Allow DELETE/UPDATE if they have WHERE clause
                if keyword in ["DELETE", "UPDATE"]:
                    if "WHERE" not in query_upper:
                        return f"{keyword} without WHERE clause is not allowed for safety"
                else:
                    return f"{keyword} operations are not allowed"

        return None

    def _apply_smart_limit(self, query: str, limit: Optional[int]) -> str:
        """Add LIMIT clause if not present in SELECT query.

        Args:
            query (str): SQL query.
            limit (Optional[int]): Limit to apply.

        Returns:
            str: Query with LIMIT applied if appropriate.
        """
        query_upper = query.upper().strip()

        # Only apply to SELECT queries without existing LIMIT
        if query_upper.startswith("SELECT") and "LIMIT" not in query_upper:
            if limit and limit <= self.max_result_rows:
                return f"{query.rstrip(';')} LIMIT {limit}"
            else:
                return f"{query.rstrip(';')} LIMIT {self.max_result_rows}"

        return query

    def _is_valid_identifier(self, identifier: str) -> bool:
        """Check if a table/column name is valid (prevents SQL injection).

        Args:
            identifier (str): Identifier to validate.

        Returns:
            bool: True if valid, False otherwise.
        """
        # Allow alphanumeric, underscore, and dot (for schema.table)
        return bool(re.match(r"^[a-zA-Z0-9_.]+$", identifier))

    def _categorize_error(self, error: Exception) -> str:
        """Categorize database error for better error messages.

        Args:
            error (Exception): The exception that occurred.

        Returns:
            str: Error category.
        """
        error_str = str(error).lower()

        if "syntax" in error_str:
            return "syntax_error"
        elif "permission" in error_str or "denied" in error_str:
            return "permission_error"
        elif "not found" in error_str or "does not exist" in error_str:
            return "not_found"
        elif "timeout" in error_str:
            return "timeout"
        elif "connection" in error_str:
            return "connection_error"
        else:
            return "unknown_error"

    def _get_error_tip(self, error_type: str) -> str:
        """Get helpful tip for error type.

        Args:
            error_type (str): Category of error.

        Returns:
            str: Helpful tip for resolving the error.
        """
        tips = {
            "syntax_error": "Check SQL syntax. Use SELECT, FROM, WHERE correctly.",
            "permission_error": "You may not have permission to access this table or perform this operation.",
            "not_found": "Table or column does not exist. Use list_tables() to see available tables.",
            "timeout": "Query took too long. Try adding filters or reducing the result set.",
            "connection_error": "Database connection issue. Check if database is accessible.",
            "unknown_error": "An unexpected error occurred. Check the error message for details.",
        }
        return tips.get(error_type, "Check query and try again.")
