from typing import Any, Dict, Optional

try:
    import psycopg2
except ImportError:
    raise ImportError(
        "`psycopg2` not installed. Please install using `pip install psycopg2`. If you face issues, try `pip install psycopg2-binary`."
    )

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info


class PostgresTools(Toolkit):
    """A basic tool to connect to a PostgreSQL database and perform read-only operations on it."""

    def __init__(
        self,
        connection: Optional[psycopg2.extensions.connection] = None,
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
        super().__init__(name="postgres_tools", **kwargs)
        self._connection: Optional[psycopg2.extensions.connection] = connection
        self.db_name: Optional[str] = db_name
        self.user: Optional[str] = user
        self.password: Optional[str] = password
        self.host: Optional[str] = host
        self.port: Optional[int] = port
        self.table_schema: str = table_schema

        self.register(self.show_tables)
        self.register(self.describe_table)
        if inspect_queries:
            self.register(self.inspect_query)
        if run_queries:
            self.register(self.run_query)
        if summarize_tables:
            self.register(self.summarize_table)
        if export_tables:
            self.register(self.export_table_to_path)

    @property
    def connection(self) -> psycopg2.extensions.connection:
        """
        Returns the Postgres psycopg2 connection.

        :return psycopg2.extensions.connection: psycopg2 connection
        """
        if self._connection is None:
            connection_kwargs: Dict[str, Any] = {}
            if self.db_name is not None:
                connection_kwargs["database"] = self.db_name
            if self.user is not None:
                connection_kwargs["user"] = self.user
            if self.password is not None:
                connection_kwargs["password"] = self.password
            if self.host is not None:
                connection_kwargs["host"] = self.host
            if self.port is not None:
                connection_kwargs["port"] = self.port
            if self.table_schema is not None:
                connection_kwargs["options"] = f"-c search_path={self.table_schema}"

            self._connection = psycopg2.connect(**connection_kwargs)
            self._connection.set_session(readonly=True)

        return self._connection

    def show_tables(self) -> str:
        """Function to show tables in the database

        :return: List of tables in the database
        """
        stmt = f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{self.table_schema}';"
        tables = self.run_query(stmt)
        log_debug(f"Tables: {tables}")
        return tables

    def describe_table(self, table: str) -> str:
        """Function to describe a table

        :param table: Table to describe
        :return: Description of the table
        """
        stmt = f"SELECT column_name, data_type, character_maximum_length FROM information_schema.columns WHERE table_name = '{table}' AND table_schema = '{self.table_schema}';"
        table_description = self.run_query(stmt)

        log_debug(f"Table description: {table_description}")
        return f"{table}\n{table_description}"

    def summarize_table(self, table: str) -> str:
        """Function to compute a number of aggregates over a table.
        The function launches a query that computes a number of aggregates over all columns,
        including min, max, avg, std and approx_unique.

        :param table: Table to summarize
        :return: Summary of the table
        """
        stmt = f"""WITH column_stats AS (
                SELECT
                    column_name,
                    data_type
                FROM
                    information_schema.columns
                WHERE
                    table_name = '{table}'
                    AND table_schema = '{self.table_schema}'
            )
            SELECT
                column_name,
                data_type,
                COUNT(COALESCE(column_name::text, '')) AS non_null_count,
                COUNT(*) - COUNT(COALESCE(column_name::text, '')) AS null_count,
                SUM(COALESCE(column_name::numeric, 0)) AS sum,
                AVG(COALESCE(column_name::numeric, 0)) AS mean,
                MIN(column_name::numeric) AS min,
                MAX(column_name::numeric) AS max,
                STDDEV(COALESCE(column_name::numeric, 0)) AS stddev
            FROM
                column_stats,
                LATERAL (
                    SELECT
                        *
                    FROM
                        {table}
                ) AS tbl
            WHERE
                data_type IN ('integer', 'numeric', 'real', 'double precision')
            GROUP BY
                column_name, data_type
            UNION ALL
            SELECT
                column_name,
                data_type,
                COUNT(COALESCE(column_name::text, '')) AS non_null_count,
                COUNT(*) - COUNT(COALESCE(column_name::text, '')) AS null_count,
                NULL AS sum,
                NULL AS mean,
                NULL AS min,
                NULL AS max,
                NULL AS stddev
            FROM
                column_stats,
                LATERAL (
                    SELECT
                        *
                    FROM
                        {table}
                ) AS tbl
            WHERE
                data_type NOT IN ('integer', 'numeric', 'real', 'double precision')
            GROUP BY
                column_name, data_type;
        """
        table_summary = self.run_query(stmt)

        log_debug(f"Table summary: {table_summary}")
        return table_summary

    def inspect_query(self, query: str) -> str:
        """Function to inspect a query and return the query plan. Always inspect your query before running them.

        :param query: Query to inspect
        :return: Query plan
        """
        stmt = f"EXPLAIN {query};"
        explain_plan = self.run_query(stmt)

        log_debug(f"Explain plan: {explain_plan}")
        return explain_plan

    def export_table_to_path(self, table: str, path: Optional[str] = None) -> str:
        """Save a table in CSV format.
        If the path is provided, the table will be saved under that path.
            Eg: If path is /tmp, the table will be saved as /tmp/table.csv
        Otherwise it will be saved in the current directory

        :param table: Table to export
        :param path: Path to export to
        :return: None
        """

        log_debug(f"Exporting Table {table} as CSV to path {path}")
        if path is None:
            path = f"{table}.csv"
        else:
            path = f"{path}/{table}.csv"

        export_statement = f"COPY {self.table_schema}.{table} TO '{path}' DELIMITER ',' CSV HEADER;"
        result = self.run_query(export_statement)
        log_debug(f"Exported {table} to {path}/{table}")

        return result

    def run_query(self, query: str) -> str:
        """Function that runs a query and returns the result.

        :param query: SQL query to run
        :return: Result of the query
        """

        # -*- Format the SQL Query
        # Remove backticks
        formatted_sql = query.replace("`", "")
        # If there are multiple statements, only run the first one
        formatted_sql = formatted_sql.split(";")[0]

        try:
            log_info(f"Running: {formatted_sql}")

            cursor = self.connection.cursor()
            cursor.execute(query)
            query_result = cursor.fetchall()

            result_output = "No output"
            if query_result is not None:
                try:
                    results_as_python_objects = query_result
                    result_rows = []
                    for row in results_as_python_objects:
                        if len(row) == 1:
                            result_rows.append(str(row[0]))
                        else:
                            result_rows.append(",".join(str(x) for x in row))

                    result_data = "\n".join(result_rows)
                    result_output = ",".join(query_result.columns) + "\n" + result_data
                except AttributeError:
                    result_output = str(query_result)

            log_debug(f"Query result: {result_output}")

            return result_output
        except Exception as e:
            return str(e)
