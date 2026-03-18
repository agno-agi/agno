import csv
from typing import Any, Dict, List, Optional

try:
    import psycopg
    from psycopg import sql
    from psycopg.connection import Connection as PgConnection
    from psycopg.rows import DictRow, dict_row
except ImportError:
    raise ImportError("`psycopg` not installed. Please install using `pip install 'psycopg-binary'`.")

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class PostgresTools(Toolkit):
    """
    A toolkit for interacting with PostgreSQL databases.

    Args:
        connection (Optional[PgConnection[DictRow]]): Existing database connection to reuse.
        db_name (Optional[str]): Database name to connect to.
        user (Optional[str]): Username for authentication.
        password (Optional[str]): Password for authentication.
        host (Optional[str]): PostgreSQL server hostname.
        port (Optional[int]): PostgreSQL server port number.
        table_schema (str): Default schema for table operations. Default is "public".
    """

    _requires_connect: bool = True

    def __init__(
        self,
        connection: Optional[PgConnection[DictRow]] = None,
        db_name: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        table_schema: str = "public",
        **kwargs,
    ):
        self._connection: Optional[PgConnection[DictRow]] = connection
        self.db_name: Optional[str] = db_name
        self.user: Optional[str] = user
        self.password: Optional[str] = password
        self.host: Optional[str] = host
        self.port: Optional[int] = port
        self.table_schema: str = table_schema

        tools: List[Any] = [
            self.show_tables,
            self.describe_table,
            self.summarize_table,
            self.inspect_query,
            self.run_query,
            self.export_table_to_path,
        ]

        super().__init__(name="postgres_tools", tools=tools, **kwargs)

    def connect(self) -> PgConnection[DictRow]:
        """
        Establish a connection to the PostgreSQL database.

        Returns:
            The database connection object.
        """
        if self._connection is not None and not self._connection.closed:
            log_debug("Connection already established, reusing existing connection")
            return self._connection

        log_debug("Establishing new PostgreSQL connection.")
        connection_kwargs: Dict[str, Any] = {"row_factory": dict_row}
        if self.db_name:
            connection_kwargs["dbname"] = self.db_name
        if self.user:
            connection_kwargs["user"] = self.user
        if self.password:
            connection_kwargs["password"] = self.password
        if self.host:
            connection_kwargs["host"] = self.host
        if self.port:
            connection_kwargs["port"] = self.port

        connection_kwargs["options"] = f"-c search_path={self.table_schema}"

        self._connection = psycopg.connect(**connection_kwargs)
        self._connection.read_only = True
        return self._connection

    def close(self) -> None:
        """Closes the database connection if it's open."""
        if self._connection and not self._connection.closed:
            log_debug("Closing PostgreSQL connection.")
            self._connection.close()
            self._connection = None

    @property
    def is_connected(self) -> bool:
        """Check if a connection is currently established."""
        return self._connection is not None and not self._connection.closed

    def _ensure_connection(self) -> PgConnection[DictRow]:
        """
        Ensure a connection exists, creating one if necessary.

        Returns:
            The database connection object.
        """
        if not self.is_connected:
            return self.connect()
        return self._connection  # type: ignore

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_connected:
            self.close()

    def _execute_query(self, query: str, params: Optional[tuple] = None) -> str:
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                log_debug("Running PostgreSQL query")
                cursor.execute(query, params)

                if cursor.description is None:
                    return cursor.statusmessage or "Query executed successfully with no output."

                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    return f"Query returned no results.\nColumns: {', '.join(columns)}"

                header = ",".join(columns)
                data_rows = [",".join(map(str, row.values())) for row in rows]
                return f"{header}\n" + "\n".join(data_rows)

        except psycopg.Error as e:
            log_error(f"Database error: {e}")
            if self._connection and not self._connection.closed:
                self._connection.rollback()
            return f"Error executing query: {e}"
        except Exception as e:
            log_error(f"An unexpected error occurred: {e}")
            return f"An unexpected error occurred: {e}"

    def show_tables(self) -> str:
        """Lists all tables in the configured schema."""

        stmt = "SELECT table_name FROM information_schema.tables WHERE table_schema = %s;"
        return self._execute_query(stmt, (self.table_schema,))

    def describe_table(self, table: str) -> str:
        """
        Provides the schema (column name, data type, is nullable) for a given table.

        Args:
            table: The name of the table to describe.

        Returns:
            A string describing the table's columns and data types.
        """
        stmt = """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s;
        """
        return self._execute_query(stmt, (self.table_schema, table))

    def summarize_table(self, table: str) -> str:
        """
        Computes and returns key summary statistics for a table's columns.

        Args:
            table: The name of the table to summarize.

        Returns:
            A string containing a summary of the table.
        """
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                # First, get column information using a parameterized query
                schema_query = """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s;
                """
                cursor.execute(schema_query, (self.table_schema, table))
                columns = cursor.fetchall()
                if not columns:
                    return f"Error: Table '{table}' not found in schema '{self.table_schema}'."

                summary_parts = [f"Summary for table: {table}\n"]
                table_identifier = sql.Identifier(self.table_schema, table)

                for col in columns:
                    col_name, data_type = col["column_name"], col["data_type"]
                    col_identifier = sql.Identifier(col_name)

                    query = None
                    if any(
                        t in data_type for t in ["integer", "numeric", "real", "double precision", "bigint", "smallint"]
                    ):
                        query = sql.SQL("""
                            SELECT
                                COUNT(*) AS total_rows,
                                COUNT({col}) AS non_null_rows,
                                MIN({col}) AS min,
                                MAX({col}) AS max,
                                AVG({col}) AS average,
                                STDDEV({col}) AS std_deviation
                            FROM {tbl};
                        """).format(col=col_identifier, tbl=table_identifier)
                    elif any(t in data_type for t in ["char", "text", "uuid"]):
                        query = sql.SQL("""
                            SELECT
                                COUNT(*) AS total_rows,
                                COUNT({col}) AS non_null_rows,
                                COUNT(DISTINCT {col}) AS unique_values,
                                AVG(LENGTH({col}::text)) as avg_length
                            FROM {tbl};
                        """).format(col=col_identifier, tbl=table_identifier)

                    if query:
                        cursor.execute(query)
                        stats = cursor.fetchone()
                        summary_parts.append(f"\n--- Column: {col_name} (Type: {data_type}) ---")
                        if stats is not None:
                            for key, value in stats.items():
                                val_str = (
                                    f"{value:.2f}" if isinstance(value, float) and value is not None else str(value)
                                )
                                summary_parts.append(f"  {key}: {val_str}")
                        else:
                            summary_parts.append("  No statistics available")

                return "\n".join(summary_parts)

        except psycopg.Error as e:
            return f"Error summarizing table: {e}"

    def inspect_query(self, query: str) -> str:
        """
        Shows the execution plan for a SQL query (using EXPLAIN).

        :param query: The SQL query to inspect.
        :return: The query's execution plan.
        """
        return self._execute_query(f"EXPLAIN {query}")

    def export_table_to_path(self, table: str, path: str) -> str:
        """
        Exports a table's data to a local CSV file.

        :param table: The name of the table to export.
        :param path: The local file path to save the file.
        :return: A confirmation message with the file path.
        """
        log_debug(f"Exporting Table {table} as CSV to local path {path}")

        table_identifier = sql.Identifier(self.table_schema, table)
        stmt = sql.SQL("SELECT * FROM {tbl};").format(tbl=table_identifier)

        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute(stmt)

                if cursor.description is None:
                    return f"Error: Query returned no description for table '{table}'."

                columns = [desc[0] for desc in cursor.description]

                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    writer.writerows(row.values() for row in cursor)

            return f"Successfully exported table '{table}' to '{path}'."
        except (psycopg.Error, IOError) as e:
            if self._connection and not self._connection.closed:
                self._connection.rollback()
            return f"Error exporting table: {e}"

    def run_query(self, query: str) -> str:
        """
        Runs a read-only SQL query and returns the result.

        :param query: The SQL query to run.
        :return: The query result as a formatted string.
        """
        return self._execute_query(query)
