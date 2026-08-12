import csv
from os import getenv
from typing import Any, Callable, Dict, List, Optional

try:
    import redshift_connector
    from redshift_connector import Connection
except ImportError:
    raise ImportError("`redshift_connector` not installed. Please install using `pip install redshift-connector`.")

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info


class RedshiftTools(Toolkit):
    """Toolkit for interacting with Amazon Redshift databases (read-only).

    Supports authentication methods: standard username/password, IAM with AWS profile,
    or IAM with explicit AWS credentials.

    Args:
        host: Redshift cluster endpoint hostname. Falls back to REDSHIFT_HOST env var.
        port: Redshift cluster port number. Defaults to 5439.
        database: Database name to connect to. Falls back to REDSHIFT_DATABASE env var.
        user: Username for standard authentication.
        password: Password for standard authentication.
        iam: Enable IAM authentication. Defaults to False.
        cluster_identifier: Redshift cluster identifier for IAM auth. Falls back to REDSHIFT_CLUSTER_IDENTIFIER env var.
        region: AWS region for IAM credential retrieval. Falls back to AWS_REGION or AWS_DEFAULT_REGION env vars.
        db_user: Database user for IAM auth. Falls back to REDSHIFT_DB_USER env var.
        access_key_id: AWS access key ID for IAM auth. Falls back to AWS_ACCESS_KEY_ID env var.
        secret_access_key: AWS secret access key for IAM auth. Falls back to AWS_SECRET_ACCESS_KEY env var.
        session_token: AWS session token for temporary credentials. Falls back to AWS_SESSION_TOKEN env var.
        profile: AWS profile name for IAM auth. Falls back to AWS_PROFILE env var.
        ssl: Enable SSL connection. Defaults to True.
        table_schema: Default schema for table operations. Defaults to "public".
        show_tables: Enable show_tables tool. Defaults to True.
        describe_table: Enable describe_table tool. Defaults to True.
        summarize_table: Enable summarize_table tool. Defaults to True.
        inspect_query: Enable inspect_query tool. Defaults to True.
        run_query: Enable run_query tool. Defaults to False (executes arbitrary SQL).
        export_table_to_path: Enable export_table_to_path tool. Defaults to False (writes files).
        all: Enable all tools. Defaults to False.
    """

    _requires_connect: bool = True

    def __init__(
        self,
        host: Optional[str] = None,
        port: int = 5439,
        database: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        iam: bool = False,
        cluster_identifier: Optional[str] = None,
        region: Optional[str] = None,
        db_user: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        session_token: Optional[str] = None,
        profile: Optional[str] = None,
        ssl: bool = True,
        table_schema: str = "public",
        show_tables: bool = True,
        describe_table: bool = True,
        summarize_table: bool = True,
        inspect_query: bool = True,
        run_query: bool = False,
        export_table_to_path: bool = False,
        all: bool = False,
        **kwargs,
    ):
        # Connection parameters
        self.host: Optional[str] = host or getenv("REDSHIFT_HOST")
        self.port: int = port
        self.database: Optional[str] = database or getenv("REDSHIFT_DATABASE")

        # Standard authentication
        self.user: Optional[str] = user
        self.password: Optional[str] = password

        # IAM authentication parameters
        self.iam: bool = iam
        self.cluster_identifier: Optional[str] = cluster_identifier or getenv("REDSHIFT_CLUSTER_IDENTIFIER")
        self.region: Optional[str] = region or getenv("AWS_REGION") or getenv("AWS_DEFAULT_REGION")
        self.db_user: Optional[str] = db_user or getenv("REDSHIFT_DB_USER")

        # AWS credentials
        self.access_key_id: Optional[str] = access_key_id or getenv("AWS_ACCESS_KEY_ID")
        self.secret_access_key: Optional[str] = secret_access_key or getenv("AWS_SECRET_ACCESS_KEY")
        self.session_token: Optional[str] = session_token or getenv("AWS_SESSION_TOKEN")
        self.profile: Optional[str] = profile or getenv("AWS_PROFILE")

        # Connection settings
        self.ssl: bool = ssl
        self.table_schema: str = table_schema

        # Connection instance
        self._connection: Optional[Connection] = None

        tools: List[Callable] = []
        if all or show_tables:
            tools.append(self.show_redshift_tables)
        if all or describe_table:
            tools.append(self.describe_redshift_table)
        if all or summarize_table:
            tools.append(self.summarize_redshift_table)
        if all or inspect_query:
            tools.append(self.inspect_redshift_query)
        if all or run_query:
            tools.append(self.run_redshift_sql)
        if all or export_table_to_path:
            tools.append(self.export_redshift_table_to_path)

        super().__init__(name="redshift_tools", tools=tools, **kwargs)

    def connect(self) -> Connection:
        """
        Establish a connection to the Redshift database.

        Returns:
            The database connection object.

        Raises:
            redshift_connector.Error: If connection fails.
        """
        if self._connection is not None:
            log_debug("Connection already established, reusing existing connection")
            return self._connection

        log_info("Establishing connection to Redshift")
        self._connection = redshift_connector.connect(**self._get_connection_kwargs())
        return self._connection

    def close(self) -> None:
        """
        Close the database connection if it exists.
        """
        if self._connection is not None:
            log_info("Closing Redshift connection")
            try:
                self._connection.close()
            except Exception:
                pass  # Connection might already be closed
            self._connection = None

    @property
    def is_connected(self) -> bool:
        """Check if a connection is currently established."""
        return self._connection is not None

    def _ensure_connection(self) -> Connection:
        """
        Ensure a connection exists, creating one if necessary.

        Returns:
            The database connection object.
        """
        if self._connection is None:
            return self.connect()
        return self._connection

    def _get_connection_kwargs(self) -> Dict[str, Any]:
        """Build connection kwargs from instance."""
        connection_kwargs: Dict[str, Any] = {}

        # Common connection parameters
        if self.host:
            connection_kwargs["host"] = self.host
        if self.port:
            connection_kwargs["port"] = self.port
        if self.database:
            connection_kwargs["database"] = self.database
        connection_kwargs["ssl"] = self.ssl

        # IAM Authentication
        if self.iam:
            connection_kwargs["iam"] = True

            # For provisioned clusters (not serverless)
            if self.cluster_identifier:
                connection_kwargs["cluster_identifier"] = self.cluster_identifier
                # db_user required for provisioned clusters with IAM
                if self.db_user:
                    connection_kwargs["db_user"] = self.db_user

            # Region for IAM credential retrieval
            if self.region:
                connection_kwargs["region"] = self.region

            # AWS credentials - either profile or explicit
            if self.profile:
                connection_kwargs["profile"] = self.profile
            else:
                # Explicit AWS credentials
                if self.access_key_id:
                    connection_kwargs["access_key_id"] = self.access_key_id
                if self.secret_access_key:
                    connection_kwargs["secret_access_key"] = self.secret_access_key
                if self.session_token:
                    connection_kwargs["session_token"] = self.session_token

        else:
            # Standard username/password authentication
            if self.user:
                connection_kwargs["user"] = self.user
            if self.password:
                connection_kwargs["password"] = self.password

        return connection_kwargs

    def _execute_query(self, query: str, params: Optional[tuple] = None) -> str:
        try:
            connection = self._ensure_connection()
            with connection.cursor() as cursor:
                log_debug("Running Redshift query")
                cursor.execute(query, params)

                if cursor.description is None:
                    return "Query executed successfully."

                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()

                if not rows:
                    return f"Query returned no results.\nColumns: {', '.join(columns)}"

                header = ",".join(columns)
                data_rows = [",".join(map(str, row)) for row in rows]
                return f"{header}\n" + "\n".join(data_rows)

        except redshift_connector.Error as e:
            log_error(f"Database error: {str(e)}")
            if self._connection:
                try:
                    self._connection.rollback()
                except Exception:
                    pass  # Connection might be closed
            return f"Error executing query: {e}"
        except Exception as e:
            log_error(f"An unexpected error occurred: {str(e)}")
            return f"An unexpected error occurred: {e}"

    def show_redshift_tables(self) -> str:
        """Lists all tables in the configured schema."""

        stmt = "SELECT table_name FROM information_schema.tables WHERE table_schema = %s;"
        return self._execute_query(stmt, (self.table_schema,))

    def describe_redshift_table(self, table: str) -> str:
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

    def summarize_redshift_table(self, table: str) -> str:
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

                # Redshift uses schema.table format for fully qualified names
                full_table_name = f'"{self.table_schema}"."{table}"'

                for col in columns:
                    col_name = col[0]
                    data_type = col[1]

                    query = None
                    if any(
                        t in data_type.lower()
                        for t in [
                            "integer",
                            "int",
                            "bigint",
                            "smallint",
                            "numeric",
                            "decimal",
                            "real",
                            "double precision",
                            "float",
                        ]
                    ):
                        query = f"""
                            SELECT
                                COUNT(*) AS total_rows,
                                COUNT("{col_name}") AS non_null_rows,
                                MIN("{col_name}") AS min,
                                MAX("{col_name}") AS max,
                                AVG("{col_name}") AS average,
                                STDDEV("{col_name}") AS std_deviation
                            FROM {full_table_name};
                        """
                    elif any(t in data_type.lower() for t in ["char", "varchar", "text", "uuid"]):
                        query = f"""
                            SELECT
                                COUNT(*) AS total_rows,
                                COUNT("{col_name}") AS non_null_rows,
                                COUNT(DISTINCT "{col_name}") AS unique_values,
                                AVG(LEN("{col_name}")) as avg_length
                            FROM {full_table_name};
                        """

                    if query:
                        cursor.execute(query)
                        stats = cursor.fetchone()
                        summary_parts.append(f"\n--- Column: {col_name} (Type: {data_type}) ---")
                        if stats is not None:
                            stats_dict = dict(zip([desc[0] for desc in cursor.description], stats))
                            for key, value in stats_dict.items():
                                val_str = (
                                    f"{value:.2f}" if isinstance(value, float) and value is not None else str(value)
                                )
                                summary_parts.append(f"  {key}: {val_str}")
                        else:
                            summary_parts.append("  No statistics available")

                return "\n".join(summary_parts)

        except redshift_connector.Error as e:
            return f"Error summarizing table: {e}"

    def inspect_redshift_query(self, query: str) -> str:
        """
        Shows the execution plan for a SQL query (using EXPLAIN).

        Args:
            query: The SQL query to inspect.

        Returns:
            The query's execution plan.
        """
        return self._execute_query(f"EXPLAIN {query}")

    def export_redshift_table_to_path(self, table: str, path: str) -> str:
        """
        Exports a table's data to a local CSV file.

        Args:
            table: The name of the table to export.
            path: The local file path to save the file.

        Returns:
            A confirmation message with the file path.
        """
        log_debug(f"Exporting table {table} to {path}")

        full_table_name = f'"{self.table_schema}"."{table}"'
        stmt = f"SELECT * FROM {full_table_name};"

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
                    writer.writerows(cursor)

            return f"Successfully exported table '{table}' to '{path}'."
        except (redshift_connector.Error, IOError) as e:
            if self._connection:
                try:
                    self._connection.rollback()
                except Exception:
                    pass  # Connection might be closed
            return f"Error exporting table: {e}"

    def run_redshift_sql(self, query: str) -> str:
        """
        Runs a read-only SQL query and returns the result.

        Args:
            query: The SQL query to run.

        Returns:
            The query result as a formatted string.
        """
        return self._execute_query(query)
