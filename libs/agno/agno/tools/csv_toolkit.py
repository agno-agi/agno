import csv
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_info, log_warning, logger


class CsvTools(Toolkit):
    def __init__(
        self,
        csvs: Optional[List[Union[str, Path]]] = None,
        row_limit: Optional[int] = None,
        duckdb_connection: Optional[Any] = None,
        duckdb_kwargs: Optional[Dict[str, Any]] = None,
        read_csv_file: bool = True,
        list_csv_files: bool = True,
        get_columns: bool = True,
        query_csv_file: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.csvs: List[Path] = []
        if csvs:
            for _csv in csvs:
                if isinstance(_csv, str):
                    self.csvs.append(Path(_csv))
                elif isinstance(_csv, Path):
                    self.csvs.append(_csv)
                else:
                    raise ValueError(f"Invalid csv file: {_csv}")
        self.row_limit = row_limit
        self.duckdb_connection: Optional[Any] = duckdb_connection
        self.duckdb_kwargs: Optional[Dict[str, Any]] = duckdb_kwargs

        tools: List[Callable] = []
        if all or read_csv_file:
            tools.append(self.read_csv_file)
        if all or list_csv_files:
            tools.append(self.list_csv_files)
        if all or get_columns:
            tools.append(self.get_columns)
        if all or query_csv_file:
            try:
                import duckdb  # noqa: F401

                tools.append(self.query_csv_file)
            except ImportError as e:
                log_warning(f"`duckdb` not installed. Query functionality disabled.: {str(e)}")

        super().__init__(name="csv_tools", tools=tools, **kwargs)

    def list_csv_files(self) -> str:
        """Returns a list of available csv files.

        Returns:
            JSON with list of csv file names.
        """
        return json.dumps([_csv.stem for _csv in self.csvs])

    def read_csv_file(self, csv_name: str, row_limit: Optional[int] = None) -> str:
        """Read the contents of a csv file.

        Args:
            csv_name: The name of the csv file to read without the extension.
            row_limit: The number of rows to return. None returns all rows.

        Returns:
            JSON with csv contents or error message.
        """
        try:
            if csv_name not in [_csv.stem for _csv in self.csvs]:
                return json.dumps(
                    {"error": f"File '{csv_name}' not found", "available": [_csv.stem for _csv in self.csvs]}
                )

            log_info(f"Reading file: {csv_name}")
            file_path = [_csv for _csv in self.csvs if _csv.stem == csv_name][0]

            # Read the csv file
            csv_data = []
            _row_limit = row_limit or self.row_limit
            with open(str(file_path), encoding="utf-8-sig", newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                if _row_limit is not None:
                    csv_data = [row for row in reader][:_row_limit]
                else:
                    csv_data = [row for row in reader]
            return json.dumps(csv_data)
        except Exception as e:
            logger.exception("Error reading csv")
            return json.dumps({"error": f"Error reading csv: {e}"})

    def get_columns(self, csv_name: str) -> str:
        """Get the columns of a csv file.

        Args:
            csv_name: The name of the csv file without the extension.

        Returns:
            JSON with list of column names or error message.
        """
        try:
            if csv_name not in [_csv.stem for _csv in self.csvs]:
                return json.dumps(
                    {"error": f"File '{csv_name}' not found", "available": [_csv.stem for _csv in self.csvs]}
                )

            log_info(f"Reading columns from file: {csv_name}")
            file_path = [_csv for _csv in self.csvs if _csv.stem == csv_name][0]

            # Get the columns of the csv file
            with open(str(file_path), encoding="utf-8-sig", newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                columns = reader.fieldnames

            return json.dumps(columns)
        except Exception as e:
            logger.exception("Error getting columns")
            return json.dumps({"error": f"Error getting columns: {e}"})

    def query_csv_file(self, csv_name: str, sql_query: str) -> str:
        """Run a SQL query on a csv file using DuckDB.

        The table name is the csv file name without extension. Use double quotes for
        column names with spaces/special chars. Use single quotes for string values.

        Args:
            csv_name: The name of the csv file to query.
            sql_query: The DuckDB SQL query to run.

        Returns:
            JSON with query results or error message.
        """
        try:
            import duckdb

            if csv_name not in [_csv.stem for _csv in self.csvs]:
                return json.dumps(
                    {"error": f"File '{csv_name}' not found", "available": [_csv.stem for _csv in self.csvs]}
                )

            # Load the csv file into duckdb
            log_info(f"Loading csv file: {csv_name}")
            file_path = [_csv for _csv in self.csvs if _csv.stem == csv_name][0]

            # Create duckdb connection
            con = self.duckdb_connection
            if not self.duckdb_connection:
                con = duckdb.connect(**(self.duckdb_kwargs or {}))
            if con is None:
                log_error("Error connecting to DuckDB")
                return json.dumps({"error": "Error connecting to DuckDB"})

            # Create a table from the csv file
            # Quote the table name so stems with hyphens or special characters are valid identifiers
            # Bind the file path as a parameter so it can't break out of the SQL statement
            table_name = csv_name.replace('"', '""')
            con.execute(
                f'CREATE TABLE "{table_name}" AS SELECT * FROM read_csv(?, ignore_errors=false, auto_detect=true)',
                [str(file_path)],
            )

            # -*- Format the SQL Query
            # Remove backticks
            formatted_sql = sql_query.replace("`", "")
            # If there are multiple statements, only run the first one
            formatted_sql = formatted_sql.split(";")[0]
            # -*- Run the SQL Query
            log_info(f"Running query: {formatted_sql}")
            query_result = con.sql(formatted_sql)
            if query_result is None:
                return json.dumps({"result": None})

            try:
                columns = query_result.columns
                rows = query_result.fetchall()
                result_data = [dict(zip(columns, row)) for row in rows]
                log_debug(f"Query result: {len(result_data)} rows")
                return json.dumps({"columns": columns, "rows": result_data}, default=str)
            except AttributeError:
                return json.dumps({"result": str(query_result)})
        except Exception as e:
            logger.exception("Error querying csv")
            return json.dumps({"error": f"Error querying csv: {e}"})
