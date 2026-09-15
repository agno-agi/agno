import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, log_warning, logger

try:
    import duckdb
except ImportError:
    raise ImportError("`duckdb` not installed. Please install using `pip install duckdb`.")


class DuckDbTools(Toolkit):
    def __init__(
        self,
        db_path: Optional[str] = None,
        connection: Optional[duckdb.DuckDBPyConnection] = None,
        init_commands: Optional[List] = None,
        read_only: bool = False,
        config: Optional[dict] = None,
        **kwargs,
    ):
        self.db_path: Optional[str] = db_path
        self.read_only: bool = read_only
        self.config: Optional[dict] = config
        self._connection: Optional[duckdb.DuckDBPyConnection] = connection
        self.init_commands: Optional[List] = init_commands
        self._reserved_keywords: Optional[frozenset] = None

        tools: List[Any] = [
            self.show_tables,
            self.describe_table,
            self.inspect_query,
            self.run_query,
            self.create_table_from_path,
            self.summarize_table,
            self.export_table_to_path,
            self.load_local_path_to_table,
            self.load_local_csv_to_table,
            self.load_s3_path_to_table,
            self.load_s3_csv_to_table,
            self.create_fts_index,
            self.full_text_search,
        ]

        super().__init__(name="duckdb_tools", tools=tools, **kwargs)

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """Returns the duckdb connection.

        Returns:
            duckdb.DuckDBPyConnection: duckdb connection
        """
        if self._connection is None:
            connection_kwargs: Dict[str, Any] = {}
            if self.db_path is not None:
                connection_kwargs["database"] = self.db_path
            if self.read_only:
                connection_kwargs["read_only"] = self.read_only
            if self.config is not None:
                connection_kwargs["config"] = self.config
            self._connection = duckdb.connect(**connection_kwargs)
            try:
                if self.init_commands is not None:
                    for command in self.init_commands:
                        self._connection.sql(command)
            except Exception as e:
                logger.exception(e)
                log_warning(f"Failed to run duckdb init commands: {str(e)}")

        return self._connection

    def show_tables(self, show_tables: bool) -> str:
        """Function to show tables in the database

        Args:
            show_tables (bool): Show tables in the database

        Returns:
            str: List of tables in the database
        """
        if show_tables:
            stmt = "SHOW TABLES;"
            tables = self.run_query(stmt)
            log_debug(f"Tables: {tables}")
            return tables
        return "No tables to show"

    def describe_table(self, table: str) -> str:
        """Function to describe a table

        Args:
            table (str): Table to describe

        Returns:
            str: Description of the table
        """
        stmt = f"DESCRIBE {table};"
        table_description = self.run_query(stmt)

        log_debug(f"Table description: {table_description}")
        return f"{table}\n{table_description}"

    def inspect_query(self, query: str) -> str:
        """Function to inspect a query and return the query plan. Always inspect your query before running them.

        Args:
            query (str): Query to inspect

        Returns:
            str: Query plan
        """
        stmt = f"explain {query};"
        explain_plan = self.run_query(stmt)

        log_debug(f"Explain plan: {explain_plan}")
        return explain_plan

    def run_query(self, query: str) -> str:
        """Function that runs a query and returns the result.

        Args:
            query (str): SQL query to run

        Returns:
            str: Result of the query
        """

        # -*- Format the SQL Query
        # Remove backticks
        formatted_sql = query.replace("`", "")
        # If there are multiple statements, only run the first one
        formatted_sql = formatted_sql.split(";")[0]

        try:
            log_info(f"Running: {formatted_sql}")

            query_result = self.connection.sql(formatted_sql)
            result_output = "No output"
            if query_result is not None:
                try:
                    results_as_python_objects = query_result.fetchall()
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
        except duckdb.ProgrammingError as e:
            return str(e)
        except duckdb.Error as e:
            return str(e)
        except Exception as e:
            return str(e)

    def summarize_table(self, table: str) -> str:
        """Function to compute a number of aggregates over a table.
        The function launches a query that computes a number of aggregates over all columns,
        including min, max, avg, std and approx_unique.

        Args:
            table (str): Table to summarize

        Returns:
            str: Summary of the table
        """
        table_summary = self.run_query(f"SUMMARIZE {table};")

        log_debug(f"Table description: {table_summary}")
        return table_summary

    def get_table_name_from_path(self, path: str) -> str:
        """Get the table name from a path

        Args:
            path (str): Path to get the table name from

        Returns:
            str: Table name
        """
        # Get the file name without extension from the path
        table = Path(path).stem
        # Replace characters that aren't valid in an unquoted SQL identifier
        table = re.sub(r"\W+", "_", table).strip("_")
        # An identifier can't be empty or start with a digit ("tbl" avoids the reserved word "table")
        if not table:
            table = "tbl"
        if table[0].isdigit():
            table = f"_{table}"
        # The agent reuses this name verbatim in later free-form SQL, so a reserved keyword would
        # break the next query even though the create succeeds. Suffix it to keep it unquoted-safe.
        if table.lower() in self._reserved_keywords_set():
            table = f"{table}_"

        return table

    def _reserved_keywords_set(self) -> frozenset:
        """Fetch and cache DuckDB's reserved keywords so derived table names stay valid identifiers."""
        if self._reserved_keywords is None:
            rows = self.connection.sql(
                "SELECT keyword_name FROM duckdb_keywords() WHERE keyword_category = 'reserved'"
            ).fetchall()
            self._reserved_keywords = frozenset(str(row[0]).lower() for row in rows)
        return self._reserved_keywords

    def _escape_sql_string(self, value: str) -> str:
        """Escape single quotes so a value is safe inside a SQL string literal."""
        return value.replace("'", "''")

    def create_table_from_path(self, path: str, table: Optional[str] = None, replace: bool = False) -> str:
        """Creates a table from a path

        Args:
            path (str): Path to load
            table (Optional[str]): Optional table name to use
            replace (bool): Whether to replace the table if it already exists

        Returns:
            str: Table name created
        """

        if table is None:
            table = self.get_table_name_from_path(path)

        log_debug(f"Creating table {table} from {path}")
        create_statement = "CREATE TABLE IF NOT EXISTS"
        if replace:
            create_statement = "CREATE OR REPLACE TABLE"

        # Check if the file is a CSV
        safe_path = self._escape_sql_string(path)
        if path.lower().endswith(".csv"):
            create_statement += (
                f" {table} AS SELECT * FROM read_csv('{safe_path}', ignore_errors=false, auto_detect=true);"
            )
        else:
            create_statement += f" {table} AS SELECT * FROM '{safe_path}';"

        self.run_query(create_statement)
        log_debug(f"Created table {table} from {path}")
        return table

    def export_table_to_path(self, table: str, format: Optional[str] = "PARQUET", path: Optional[str] = None) -> str:
        """Save a table in a desired format (default: parquet)
        If the path is provided, the table will be saved under that path.
            Eg: If path is /tmp, the table will be saved as /tmp/table.parquet
        Otherwise it will be saved in the current directory

        Args:
            table (str): Table to export
            format (Optional[str]): Format to export in (default: parquet)
            path (Optional[str]): Path to export to

        Returns:
            str: Result of the export query
        """
        if format is None:
            format = "PARQUET"

        log_debug(f"Exporting Table {table} as {format.upper()} to path {path}")
        if path is None:
            path = f"{table}.{format}"
        else:
            path = f"{path}/{table}.{format}"
        export_statement = (
            f"COPY (SELECT * FROM {table}) TO '{self._escape_sql_string(path)}' (FORMAT {format.upper()});"
        )
        result = self.run_query(export_statement)
        log_debug(f"Exported {table} to {path}/{table}")
        return result

    def load_local_path_to_table(self, path: str, table: Optional[str] = None) -> Tuple[str, str]:
        """Load a local file into duckdb

        Args:
            path (str): Path to load
            table (Optional[str]): Optional table name to use

        Returns:
            Tuple[str, str]: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")

        if table is None:
            table = self.get_table_name_from_path(path)

        create_statement = f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM '{self._escape_sql_string(path)}';"
        self.run_query(create_statement)

        log_debug(f"Loaded {path} into duckdb as {table}")
        return table, create_statement

    def load_local_csv_to_table(
        self, path: str, table: Optional[str] = None, delimiter: Optional[str] = None
    ) -> Tuple[str, str]:
        """Load a local CSV file into duckdb

        Args:
            path (str): Path to load
            table (Optional[str]): Optional table name to use
            delimiter (Optional[str]): Optional delimiter to use

        Returns:
            Tuple[str, str]: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")

        if table is None:
            table = self.get_table_name_from_path(path)

        select_statement = (
            f"SELECT * FROM read_csv('{self._escape_sql_string(path)}', ignore_errors=false, auto_detect=true"
        )
        if delimiter is not None:
            select_statement += f", delim='{delimiter}')"
        else:
            select_statement += ")"

        create_statement = f"CREATE OR REPLACE TABLE {table} AS {select_statement};"
        self.run_query(create_statement)

        log_debug(f"Loaded CSV {path} into duckdb as {table}")
        return table, create_statement

    def load_s3_path_to_table(self, path: str, table: Optional[str] = None) -> Tuple[str, str]:
        """Load a file from S3 into duckdb

        Args:
            path (str): S3 path to load
            table (Optional[str]): Optional table name to use

        Returns:
            Tuple[str, str]: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")

        if table is None:
            table = self.get_table_name_from_path(path)

        create_statement = f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM '{self._escape_sql_string(path)}';"
        self.run_query(create_statement)

        log_debug(f"Loaded {path} into duckdb as {table}")
        return table, create_statement

    def load_s3_csv_to_table(
        self, path: str, table: Optional[str] = None, delimiter: Optional[str] = None
    ) -> Tuple[str, str]:
        """Load a CSV file from S3 into duckdb

        Args:
            path (str): S3 path to load
            table (Optional[str]): Optional table name to use
            delimiter (Optional[str]): Optional delimiter to use

        Returns:
            Tuple[str, str]: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")

        if table is None:
            table = self.get_table_name_from_path(path)

        select_statement = (
            f"SELECT * FROM read_csv('{self._escape_sql_string(path)}', ignore_errors=false, auto_detect=true"
        )
        if delimiter is not None:
            select_statement += f", delim='{delimiter}')"
        else:
            select_statement += ")"

        create_statement = f"CREATE OR REPLACE TABLE {table} AS {select_statement};"
        self.run_query(create_statement)

        log_debug(f"Loaded CSV {path} into duckdb as {table}")
        return table, create_statement

    def create_fts_index(self, table: str, unique_key: str, input_values: list[str]) -> str:
        """Create a full text search index on a table

        Args:
            table (str): Table to create the index on
            unique_key (str): Unique key to use
            input_values (list[str]): Values to index

        Returns:
            str: Result of the create index query
        """
        log_debug(f"Creating FTS index on {table} for {input_values}")
        self.run_query("INSTALL fts;")
        log_debug("Installed FTS extension")
        self.run_query("LOAD fts;")
        log_debug("Loaded FTS extension")

        # Each indexed column is a separate PRAGMA argument, not one list literal
        input_value_literals = ", ".join(f"'{self._escape_sql_string(value)}'" for value in input_values)
        create_fts_index_statement = (
            f"PRAGMA create_fts_index("
            f"'{self._escape_sql_string(table)}', '{self._escape_sql_string(unique_key)}', {input_value_literals});"
        )
        log_debug(f"Running {create_fts_index_statement}")
        result = self.run_query(create_fts_index_statement)
        log_debug(f"Created FTS index on {table} for {input_values}")

        return result

    def _fts_schema_name(self, table: str) -> str:
        """Get the FTS macro schema DuckDB creates for a table, quoted as an identifier.

        DuckDB names it fts_<schema>_<table>, so a schema-qualified table lands in
        fts_<schema>_<table> rather than fts_main_<table>.
        """
        parts = table.split(".")
        schema = parts[0] if len(parts) > 1 else "main"
        name = f"fts_{schema}_{parts[-1]}"
        return '"' + name.replace('"', '""') + '"'

    def full_text_search(self, table: str, unique_key: str, search_text: str) -> str:
        """Full text Search in a table column for a specific text/keyword

        Args:
            table (str): Table to search
            unique_key (str): Unique key to use
            search_text (str): Text to search

        Returns:
            str: Search results
        """
        log_debug(f"Running full_text_search for {search_text} in {table}")
        fts_schema = self._fts_schema_name(table)
        search_text_statement = f"""SELECT {fts_schema}.match_bm25({unique_key}, '{self._escape_sql_string(search_text)}') AS score,*
                                        FROM {table}
                                        WHERE score IS NOT NULL
                                        ORDER BY score;"""

        log_debug(f"Running {search_text_statement}")
        result = self.run_query(search_text_statement)
        log_debug(f"Search results for {search_text} in {table}")

        return result
