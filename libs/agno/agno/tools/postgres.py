import csv
from typing import Any, Dict, List, Optional

try:
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import connection as PgConnection
    from psycopg2.extras import DictCursor
except ImportError:
    raise ImportError(
        "`psycopg2` not installed. Please install using `pip install psycopg2`. If you face issues, try `pip install psycopg2-binary`."
    )

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error


class PostgresTools(Toolkit):
    def __init__(
        self,
        connection: Optional[PgConnection] = None,
        db_name: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        run_queries: bool = True,
        inspect_queries: bool = False,
        summarize_tables: bool = True,
        export_tables: bool = False,
        table_schema: str = "public",
        **kwargs,
    ):
        self._connection: Optional[PgConnection] = connection
        self.db_name: Optional[str] = db_name
        self.user: Optional[str] = user
        self.password: Optional[str] = password
        self.host: Optional[str] = host
        self.port: Optional[int] = port
        self.table_schema: str = table_schema

        tools: List[Any] = [
            self.show_tables,
            self.describe_table,
        ]
        if inspect_queries:
            tools.append(self.inspect_query)
        if run_queries:
            tools.append(self.run_query)
        if summarize_tables:
            tools.append(self.summarize_table)
        if export_tables:
            tools.append(self.export_table_to_path)

        super().__init__(name="postgres_tools", tools=tools, **kwargs)

    @property
    def connection(self) -> PgConnection:
        """
        Returns the Postgres psycopg2 connection.
        :return psycopg2.extensions.connection: psycopg2 connection
        """
        if self._connection is None or self._connection.closed:
            log_debug("Establishing new PostgreSQL connection.")
            connection_kwargs: Dict[str, Any] = {"cursor_factory": DictCursor}
            if self.db_name:
                connection_kwargs["database"] = self.db_name
            if self.user:
                connection_kwargs["user"] = self.user
            if self.password:
                connection_kwargs["password"] = self.password
            if self.host:
                connection_kwargs["host"] = self.host
            if self.port:
                connection_kwargs["port"] = self.port

            connection_kwargs["options"] = f"-c search_path={self.table_schema}"

            self._connection = psycopg2.connect(**connection_kwargs)
            self._connection.set_session(readonly=True)

        return self._connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def close(self):
        """Closes the database connection if it's open."""
        if self._connection and not self._connection.closed:
            log_debug("Closing PostgreSQL connection.")
            self._connection.close()
            self._connection = None

    def _execute_query(self, query: str, params: Optional[tuple] = None) -> str:
        try:
            with self.connection.cursor() as cursor:
                log_debug(f"Running PostgreSQL Query: {query} with Params: {params}")
                cursor.execute(query, params)

                if cursor.description is None:
                    return cursor.statusmessage or "Query executed successfully with no output."

                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    return f"Query returned no results.\nColumns: {', '.join(columns)}"

                header = ",".join(columns)
                data_rows = [",".join(map(str, row)) for row in rows]
                return f"{header}\n" + "\n".join(data_rows)

        except psycopg2.Error as e:
            log_error(f"Database error: {e}")
            if self.connection and not self.connection.closed:
                self.connection.rollback()
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
            with self.connection.cursor() as cursor:
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
                        for key, value in stats.items():
                            val_str = (
                                f"{value:.2f}" if isinstance(value, (float, int)) and value is not None else str(value)
                            )
                            summary_parts.append(f"  {key}: {val_str}")

                return "\n".join(summary_parts)

        except psycopg2.Error as e:
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
            with self.connection.cursor() as cursor:
                cursor.execute(stmt)
                columns = [desc[0] for desc in cursor.description]

                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(columns)
                    writer.writerows(cursor)

            return f"Successfully exported table '{table}' to '{path}'."
        except (psycopg2.Error, IOError) as e:
            return f"Error exporting table: {e}"

    def run_query(self, query: str) -> str:
        """
        Runs a read-only SQL query and returns the result.

        :param query: The SQL query to run.
        :return: The query result as a formatted string.
        """
        return self._execute_query(query)
