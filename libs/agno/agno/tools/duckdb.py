from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agno.tools import Toolkit
from agno.tools._security import (
    assert_read_only_sql,
    resolve_within,
    validate_sql_identifier,
)
from agno.utils.log import log_debug, log_error, log_info, log_warning, logger

try:
    import duckdb
except ImportError:
    raise ImportError("`duckdb` not installed. Please install using `pip install duckdb`.")


def _q(ident: str) -> str:
    """Validate and double-quote an identifier for DuckDB.

    Args:
        ident: Raw identifier string.

    Returns:
        ``ident`` wrapped in double-quotes with embedded quotes doubled.

    Raises:
        ValueError: If ``ident`` is not a safe SQL identifier.
    """
    validated = validate_sql_identifier(ident)
    return '"' + validated.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    """Quote a value as a single-quoted SQL string literal.

    Args:
        value: The string literal to quote.

    Returns:
        The value wrapped in single quotes with embedded quotes doubled.

    Raises:
        ValueError: If ``value`` is not a string.
    """
    if not isinstance(value, str):
        raise ValueError("SQL string literal must be a str")
    return "'" + value.replace("'", "''") + "'"


class DuckDbTools(Toolkit):
    """DuckDB toolkit.

    Security notes (hardened build):

    * Identifiers (table names, unique keys) are validated and
      double-quoted before being interpolated into SQL. Values are
      bound or single-quoted with escaping via :func:`_quote_literal`.
    * :meth:`run_query` refuses any statement other than
      ``SELECT`` / ``WITH`` when ``read_only=True`` (the default).
    * Path-using tools (:meth:`create_table_from_path`,
      :meth:`export_table_to_path`, ``load_local_*``) refuse paths
      that escape ``allowed_paths_base`` when that option is set.
      Remote schemes (``s3://``, ``http://``, ``https://``) bypass
      the filesystem containment check because they target no local
      file; the deployer is responsible for network-level controls.
    * :meth:`create_fts_index` and :meth:`full_text_search` run
      ``INSTALL`` / ``LOAD`` and are considered write-like; they are
      registered only when ``enable_fts=True``.

    Args:
        db_path: Optional path to the DuckDB database file. When
            omitted, DuckDB opens an in-memory database.
        connection: Optional pre-built DuckDB connection to reuse.
        init_commands: Iterable of SQL statements run immediately
            after connection setup.
        read_only: When True (default), opens the connection in
            read-only mode and refuses writing tools.
        config: Optional DuckDB config dictionary.
        allowed_paths_base: Optional root path for filesystem-based
            load/export tools. Paths outside this root are refused.
        enable_fts: Register the full-text search tools.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        connection: Optional[duckdb.DuckDBPyConnection] = None,
        init_commands: Optional[Iterable[str]] = None,
        read_only: bool = True,
        config: Optional[dict] = None,
        allowed_paths_base: Optional[str] = None,
        enable_fts: bool = False,
        **kwargs,
    ):
        self.db_path: Optional[str] = db_path
        self.read_only: bool = read_only
        self.config: Optional[dict] = config
        self._connection: Optional[duckdb.DuckDBPyConnection] = connection
        self.init_commands: Optional[List[str]] = list(init_commands) if init_commands is not None else None
        self._allowed_paths_base: Optional[Path] = Path(allowed_paths_base).resolve() if allowed_paths_base else None

        tools: List[Any] = [
            self.show_tables,
            self.describe_table,
            self.inspect_query,
            self.run_query,
            self.summarize_table,
        ]
        if not self.read_only:
            tools.extend(
                [
                    self.create_table_from_path,
                    self.export_table_to_path,
                    self.load_local_path_to_table,
                    self.load_local_csv_to_table,
                    self.load_s3_path_to_table,
                    self.load_s3_csv_to_table,
                ]
            )
        if enable_fts:
            tools.extend([self.create_fts_index, self.full_text_search])

        super().__init__(name="duckdb_tools", tools=tools, **kwargs)

    def _check_path_allowed(self, path: str) -> Optional[str]:
        """Return a reason string if ``path`` escapes the allowed root.

        Remote schemes (``s3://``, ``http://``, ``https://``) are
        always permitted since they target no local file; filesystem
        containment does not apply.
        """
        if self._allowed_paths_base is None:
            return None
        if path.startswith(("s3://", "http://", "https://")):
            return None
        ok, _ = resolve_within(path, self._allowed_paths_base)
        if not ok:
            return f"Path '{path}' is outside the configured allowed base directory {self._allowed_paths_base!s}."
        return None

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        """
        Returns the duckdb connection

        :return duckdb.DuckDBPyConnection: duckdb connection
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

        :param show_tables: Show tables in the database
        :return: List of tables in the database
        """
        if show_tables:
            stmt = "SHOW TABLES;"
            tables = self.run_query(stmt)
            log_debug(f"Tables: {tables}")
            return tables
        return "No tables to show"

    def describe_table(self, table: str) -> str:
        """Function to describe a table

        :param table: Table to describe
        :return: Description of the table
        """
        try:
            stmt = f"DESCRIBE {_q(table)};"
        except ValueError as e:
            return f"Error: {e}"
        table_description = self._run_raw(stmt)

        log_debug(f"Table description: {table_description}")
        return f"{table}\n{table_description}"

    def inspect_query(self, query: str) -> str:
        """Function to inspect a query and return the query plan. Always inspect your query before running them.

        :param query: Query to inspect
        :return: Query plan
        """
        try:
            safe_q = assert_read_only_sql(query)
        except ValueError as e:
            return f"Error: {e}"
        stmt = f"EXPLAIN {safe_q}"
        explain_plan = self._run_raw(stmt)

        log_debug(f"Explain plan: {explain_plan}")
        return explain_plan

    def run_query(self, query: str) -> str:
        """Function that runs a query and returns the result.

        :param query: SQL query to run
        :return: Result of the query
        """
        if self.read_only:
            try:
                assert_read_only_sql(query)
            except ValueError as e:
                log_warning(f"DuckDbTools rejected query: {e}")
                return f"Error: {e}"

        formatted_sql = query.replace("`", "").split(";")[0]
        return self._run_raw(formatted_sql)

    def _run_raw(self, formatted_sql: str) -> str:
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

        :param table: Table to summarize
        :return: Summary of the table
        """
        try:
            stmt = f"SUMMARIZE {_q(table)};"
        except ValueError as e:
            return f"Error: {e}"
        table_summary = self._run_raw(stmt)

        log_debug(f"Table description: {table_summary}")
        return table_summary

    def get_table_name_from_path(self, path: str) -> str:
        """Get the table name from a path

        :param path: Path to get the table name from
        :return: Table name
        """
        # Get the file name from the path
        path_obj = Path(path)
        # Get the file name without extension from the path
        table = path_obj.stem
        # If the table isn't a valid SQL identifier, we'll need to use something else
        table = table.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")

        return table

    def create_table_from_path(self, path: str, table: Optional[str] = None, replace: bool = False) -> str:
        """Creates a table from a path

        :param path: Path to load
        :param table: Optional table name to use
        :param replace: Whether to replace the table if it already exists
        :return: Table name created
        """

        if table is None:
            table = self.get_table_name_from_path(path)
        try:
            table_ident = _q(table)
        except ValueError as e:
            return f"Error: {e}"
        err = self._check_path_allowed(path)
        if err:
            log_error(err)
            return f"Error: {err}"

        log_debug(f"Creating table {table} from {path}")
        create_statement = "CREATE TABLE IF NOT EXISTS"
        if replace:
            create_statement = "CREATE OR REPLACE TABLE"

        path_literal = _quote_literal(path)
        if path.lower().endswith(".csv"):
            create_statement += (
                f" {table_ident} AS SELECT * FROM read_csv({path_literal}, ignore_errors=false, auto_detect=true);"
            )
        else:
            create_statement += f" {table_ident} AS SELECT * FROM {path_literal};"

        self._run_raw(create_statement)
        log_debug(f"Created table {table} from {path}")
        return table

    def export_table_to_path(self, table: str, format: Optional[str] = "PARQUET", path: Optional[str] = None) -> str:
        """Save a table in a desired format (default: parquet)
        If the path is provided, the table will be saved under that path.
            Eg: If path is /tmp, the table will be saved as /tmp/table.parquet
        Otherwise it will be saved in the current directory

        :param table: Table to export
        :param format: Format to export in (default: parquet)
        :param path: Path to export to
        :return: None
        """
        if format is None:
            format = "PARQUET"
        fmt_up = format.upper()
        if not fmt_up.isalpha():
            return f"Error: invalid format {format!r}"
        try:
            table_ident = _q(table)
        except ValueError as e:
            return f"Error: {e}"

        log_debug(f"Exporting Table {table} as {fmt_up} to path {path}")
        if path is None:
            path = f"{table}.{format}"
        else:
            path = f"{path}/{table}.{format}"
        err = self._check_path_allowed(path)
        if err:
            log_error(err)
            return f"Error: {err}"

        export_statement = f"COPY (SELECT * FROM {table_ident}) TO {_quote_literal(path)} (FORMAT {fmt_up});"
        result = self._run_raw(export_statement)
        log_debug(f"Exported {table} to {path}")
        return result

    def _build_load_statement(
        self,
        path: str,
        table: Optional[str],
        is_csv: bool,
        delimiter: Optional[str],
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Build a CREATE TABLE ... AS SELECT statement.

        Returns:
            ``(table_name, statement, error)``. When ``error`` is not
            None the other fields are undefined and the caller should
            surface the error directly.
        """
        err = self._check_path_allowed(path)
        if err:
            return None, None, f"Error: {err}"
        if table is None:
            table = self.get_table_name_from_path(path)
        try:
            table_ident = _q(table)
        except ValueError as e:
            return None, None, f"Error: {e}"

        path_literal = _quote_literal(path)
        if is_csv:
            select_statement = f"SELECT * FROM read_csv({path_literal}, ignore_errors=false, auto_detect=true"
            if delimiter is not None:
                if len(delimiter) > 4 or "'" in delimiter:
                    return None, None, "Error: invalid delimiter"
                select_statement += f", delim={_quote_literal(delimiter)})"
            else:
                select_statement += ")"
            create_statement = f"CREATE OR REPLACE TABLE {table_ident} AS {select_statement};"
        else:
            create_statement = f"CREATE OR REPLACE TABLE {table_ident} AS SELECT * FROM {path_literal};"
        return table, create_statement, None

    def load_local_path_to_table(self, path: str, table: Optional[str] = None) -> Tuple[str, str]:
        """Load a local file into duckdb

        :param path: Path to load
        :param table: Optional table name to use
        :return: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")
        resolved_table, stmt, err = self._build_load_statement(path, table, is_csv=False, delimiter=None)
        if err is not None:
            return "", err
        assert stmt is not None and resolved_table is not None
        self._run_raw(stmt)
        log_debug(f"Loaded {path} into duckdb as {resolved_table}")
        return resolved_table, stmt

    def load_local_csv_to_table(
        self, path: str, table: Optional[str] = None, delimiter: Optional[str] = None
    ) -> Tuple[str, str]:
        """Load a local CSV file into duckdb

        :param path: Path to load
        :param table: Optional table name to use
        :param delimiter: Optional delimiter to use
        :return: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")
        resolved_table, stmt, err = self._build_load_statement(path, table, is_csv=True, delimiter=delimiter)
        if err is not None:
            return "", err
        assert stmt is not None and resolved_table is not None
        self._run_raw(stmt)
        log_debug(f"Loaded CSV {path} into duckdb as {resolved_table}")
        return resolved_table, stmt

    def load_s3_path_to_table(self, path: str, table: Optional[str] = None) -> Tuple[str, str]:
        """Load a file from S3 into duckdb

        :param path: S3 path to load
        :param table: Optional table name to use
        :return: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")
        resolved_table, stmt, err = self._build_load_statement(path, table, is_csv=False, delimiter=None)
        if err is not None:
            return "", err
        assert stmt is not None and resolved_table is not None
        self._run_raw(stmt)
        log_debug(f"Loaded {path} into duckdb as {resolved_table}")
        return resolved_table, stmt

    def load_s3_csv_to_table(
        self, path: str, table: Optional[str] = None, delimiter: Optional[str] = None
    ) -> Tuple[str, str]:
        """Load a CSV file from S3 into duckdb

        :param path: S3 path to load
        :param table: Optional table name to use
        :return: Table name, SQL statement used to load the file
        """
        log_debug(f"Loading {path} into duckdb")
        resolved_table, stmt, err = self._build_load_statement(path, table, is_csv=True, delimiter=delimiter)
        if err is not None:
            return "", err
        assert stmt is not None and resolved_table is not None
        self._run_raw(stmt)
        log_debug(f"Loaded CSV {path} into duckdb as {resolved_table}")
        return resolved_table, stmt

    def create_fts_index(self, table: str, unique_key: str, input_values: list[str]) -> str:
        """Create a full text search index on a table

        :param table: Table to create the index on
        :param unique_key: Unique key to use
        :param input_values: Values to index
        :return: None
        """
        try:
            table_ident = validate_sql_identifier(table)
            key_ident = validate_sql_identifier(unique_key)
        except ValueError as e:
            return f"Error: {e}"
        if not isinstance(input_values, list) or not all(isinstance(v, str) for v in input_values):
            return "Error: input_values must be a list of strings"
        for v in input_values:
            try:
                validate_sql_identifier(v)
            except ValueError as e:
                return f"Error: {e}"

        log_debug(f"Creating FTS index on {table_ident} for {input_values}")
        self._run_raw("INSTALL fts;")
        log_debug("Installed FTS extension")
        self._run_raw("LOAD fts;")
        log_debug("Loaded FTS extension")

        values_literal = ", ".join(_quote_literal(v) for v in input_values)
        create_fts_index_statement = (
            f"PRAGMA create_fts_index({_quote_literal(table_ident)}, {_quote_literal(key_ident)}, {values_literal});"
        )
        log_debug(f"Running {create_fts_index_statement}")
        result = self._run_raw(create_fts_index_statement)
        log_debug(f"Created FTS index on {table_ident} for {input_values}")

        return result

    def full_text_search(self, table: str, unique_key: str, search_text: str) -> str:
        """Full text Search in a table column for a specific text/keyword

        :param table: Table to search
        :param unique_key: Unique key to use
        :param search_text: Text to search
        :return: None
        """
        try:
            table_ident = _q(table)
            key_ident = validate_sql_identifier(unique_key)
        except ValueError as e:
            return f"Error: {e}"
        if not isinstance(search_text, str):
            return "Error: search_text must be a string"

        log_debug(f"Running full_text_search for {search_text} in {table}")
        search_text_statement = (
            f"SELECT fts_main_corpus.match_bm25({key_ident}, "
            f"{_quote_literal(search_text)}) AS score, * "
            f"FROM {table_ident} "
            f"WHERE score IS NOT NULL ORDER BY score;"
        )

        log_debug(f"Running {search_text_statement}")
        result = self._run_raw(search_text_statement)
        log_debug(f"Search results for {search_text} in {table}")

        return result
