from typing import Any, Dict, List, Optional, Tuple

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_info, logger

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
        run_queries: bool = True,
        inspect_queries: bool = False,
        create_tables: bool = True,
        summarize_tables: bool = True,
        export_tables: bool = False,
        **kwargs,
    ):
        self.db_path: Optional[str] = db_path
        self.read_only: bool = read_only
        self.config: Optional[dict] = config
        self._connection: Optional[duckdb.DuckDBPyConnection] = connection
        self.init_commands: Optional[List] = init_commands

        tools: List[Any] = []
        tools.append(self.show_tables)
        tools.append(self.describe_table)

        if inspect_queries:
            tools.append(self.inspect_query)
        if run_queries:
            tools.append(self.run_query)
        if create_tables:
            tools.append(self.create_table_from_path)
        if summarize_tables:
            tools.append(self.summarize_table)
        if export_tables:
            tools.append(self.export_table_to_path)

        super().__init__(name="duckdb_tools", tools=tools, **kwargs)

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
                logger.warning("Failed to run duckdb init commands")

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
        stmt = f"DESCRIBE {table};"
        table_description = self.run_query(stmt)

        log_debug(f"Table description: {table_description}")
        return f"{table}\n{table_description}"

    def inspect_query(self, query: str) -> str:
        """Function to inspect a query and return the query plan. Always inspect your query before running them.

        :param query: Query to inspect
        :return: Query plan
        """
        stmt = f"explain {query};"
        explain_plan = self.run_query(stmt)

        log_debug(f"Explain plan: {explain_plan}")
        return explain_plan

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
        table_summary = self.run_query(f"SUMMARIZE {table};")

        log_debug(f"Table description: {table_summary}")
        return table_summary

    def get_table_name_from_path(self, path: str) -> str:
        """Get the table name from a path

        :param path: Path to get the table name from
        :return: Table name
        """
        import os

        # Get the file name from the path
        file_name = path.split("/")[-1]
        # Get the file name without extension from the path
        table, extension = os.path.splitext(file_name)
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

        log_debug(f"Creating table {table} from {path}")
        create_statement = "CREATE TABLE IF NOT EXISTS"
        if replace:
            create_statement = "CREATE OR REPLACE TABLE"

        create_statement += f" '{table}' AS SELECT * FROM '{path}';"
        self.run_query(create_statement)
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

        log_debug(f"Exporting Table {table} as {format.upper()} to path {path}")
        if path is None:
            path = f"{table}.{format}"
        else:
            path = f"{path}/{table}.{format}"
        export_statement = f"COPY (SELECT * FROM {table}) TO '{path}' (FORMAT {format.upper()});"
        result = self.run_query(export_statement)
        log_debug(f"Exported {table} to {path}/{table}")
        return result

    def load_local_path_to_table(self, path: str, table: Optional[str] = None) -> Tuple[str, str]:
        """Load a local file into duckdb

        :param path: Path to load
        :param table: Optional table name to use
        :return: Table name, SQL statement used to load the file
        """
        import os

        log_debug(f"Loading {path} into duckdb")

        if table is None:
            # Get the file name from the s3 path
            file_name = path.split("/")[-1]
            # Get the file name without extension from the s3 path
            table, extension = os.path.splitext(file_name)
            # If the table isn't a valid SQL identifier, we'll need to use something else
            table = table.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")

        create_statement = f"CREATE OR REPLACE TABLE '{table}' AS SELECT * FROM '{path}';"
        self.run_query(create_statement)

        log_debug(f"Loaded {path} into duckdb as {table}")
        return table, create_statement

    def load_local_csv_to_table(
        self, path: str, table: Optional[str] = None, delimiter: Optional[str] = None
    ) -> Tuple[str, str]:
        """Load a local CSV file into duckdb

        :param path: Path to load
        :param table: Optional table name to use
        :param delimiter: Optional delimiter to use
        :return: Table name, SQL statement used to load the file
        """
        import os

        log_debug(f"Loading {path} into duckdb")

        if table is None:
            # Get the file name from the s3 path
            file_name = path.split("/")[-1]
            # Get the file name without extension from the s3 path
            table, extension = os.path.splitext(file_name)
            # If the table isn't a valid SQL identifier, we'll need to use something else
            table = table.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")

        select_statement = f"SELECT * FROM read_csv('{path}'"
        if delimiter is not None:
            select_statement += f", delim='{delimiter}')"
        else:
            select_statement += ")"

        create_statement = f"CREATE OR REPLACE TABLE '{table}' AS {select_statement};"
        self.run_query(create_statement)

        log_debug(f"Loaded CSV {path} into duckdb as {table}")
        return table, create_statement

    def load_s3_path_to_table(self, path: str, table: Optional[str] = None) -> Tuple[str, str]:
        """Load a file from S3 into duckdb

        :param path: S3 path to load
        :param table: Optional table name to use
        :return: Table name, SQL statement used to load the file
        """
        import os

        log_debug(f"Loading {path} into duckdb")

        if table is None:
            # Get the file name from the s3 path
            file_name = path.split("/")[-1]
            # Get the file name without extension from the s3 path
            table, extension = os.path.splitext(file_name)
            # If the table isn't a valid SQL identifier, we'll need to use something else
            table = table.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")

        create_statement = f"CREATE OR REPLACE TABLE '{table}' AS SELECT * FROM '{path}';"
        self.run_query(create_statement)

        log_debug(f"Loaded {path} into duckdb as {table}")
        return table, create_statement

    def load_s3_csv_to_table(
        self, path: str, table: Optional[str] = None, delimiter: Optional[str] = None
    ) -> Tuple[str, str]:
        """Load a CSV file from S3 into duckdb

        :param path: S3 path to load
        :param table: Optional table name to use
        :return: Table name, SQL statement used to load the file
        """
        import os

        log_debug(f"Loading {path} into duckdb")

        if table is None:
            # Get the file name from the s3 path
            file_name = path.split("/")[-1]
            # Get the file name without extension from the s3 path
            table, extension = os.path.splitext(file_name)
            # If the table isn't a valid SQL identifier, we'll need to use something else
            table = table.replace("-", "_").replace(".", "_").replace(" ", "_").replace("/", "_")

        select_statement = f"SELECT * FROM read_csv('{path}'"
        if delimiter is not None:
            select_statement += f", delim='{delimiter}')"
        else:
            select_statement += ")"

        create_statement = f"CREATE OR REPLACE TABLE '{table}' AS {select_statement};"
        self.run_query(create_statement)

        log_debug(f"Loaded CSV {path} into duckdb as {table}")
        return table, create_statement

    def create_fts_index(self, table: str, unique_key: str, input_values: list[str]) -> str:
        """Create a full text search index on a table

        :param table: Table to create the index on
        :param unique_key: Unique key to use
        :param input_values: Values to index
        :return: None
        """
        log_debug(f"Creating FTS index on {table} for {input_values}")
        self.run_query("INSTALL fts;")
        log_debug("Installed FTS extension")
        self.run_query("LOAD fts;")
        log_debug("Loaded FTS extension")

        create_fts_index_statement = f"PRAGMA create_fts_index('{table}', '{unique_key}', '{input_values}');"
        log_debug(f"Running {create_fts_index_statement}")
        result = self.run_query(create_fts_index_statement)
        log_debug(f"Created FTS index on {table} for {input_values}")

        return result

    def full_text_search(self, table: str, unique_key: str, search_text: str) -> str:
        """Full text Search in a table column for a specific text/keyword

        :param table: Table to search
        :param unique_key: Unique key to use
        :param search_text: Text to search
        :return: None
        """
        log_debug(f"Running full_text_search for {search_text} in {table}")
        search_text_statement = f"""SELECT fts_main_corpus.match_bm25({unique_key}, '{search_text}') AS score,*
                                        FROM {table}
                                        WHERE score IS NOT NULL
                                        ORDER BY score;"""

        log_debug(f"Running {search_text_statement}")
        result = self.run_query(search_text_statement)
        log_debug(f"Search results for {search_text} in {table}")

        return result
