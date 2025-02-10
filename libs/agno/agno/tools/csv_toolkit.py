import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agno.tools import Toolkit
from agno.utils.log import logger


class CsvTools(Toolkit):
    def __init__(
        self,
        csvs: Optional[List[Union[str, Path]]] = None,
        row_limit: Optional[int] = None,
        read_csvs: bool = True,
        list_csvs: bool = True,
        query_csvs: bool = True,
        read_column_names: bool = True,
        duckdb_connection: Optional[Any] = None,
        duckdb_kwargs: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name="csv_tools")

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

        if read_csvs:
            self.register(self.read_csv_file)
        if list_csvs:
            self.register(self.list_csv_files)
        if read_column_names:
            self.register(self.get_columns)
        if query_csvs:
            try:
                import duckdb  # noqa: F401
            except ImportError:
                raise ImportError("`duckdb` not installed. Please install using `pip install duckdb`.")
            self.register(self.query_csv_file)

    def list_csv_files(self) -> str:
        """Returns a list of available csv files

        Returns:
            str: List of available csv files
        """
        return json.dumps([_csv.stem for _csv in self.csvs])

    def read_csv_file(self, csv_name: str, row_limit: Optional[int] = None) -> str:
        """Use this function to read the contents of a csv file `name` without the extension.

        Args:
            csv_name (str): The name of the csv file to read without the extension.
            row_limit (Optional[int]): The number of rows to return. None returns all rows. Defaults to None.

        Returns:
            str: The contents of the csv file if successful, otherwise returns an error message.
        """
        try:
            if csv_name not in [_csv.stem for _csv in self.csvs]:
                return f"File: {csv_name} not found, please use one of {self.list_csv_files()}"

            logger.info(f"Reading file: {csv_name}")
            file_path = [_csv for _csv in self.csvs if _csv.stem == csv_name][0]

            # Read the csv file
            csv_data = []
            _row_limit = row_limit or self.row_limit
            with open(str(file_path), newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                if _row_limit is not None:
                    csv_data = [row for row in reader][:_row_limit]
                else:
                    csv_data = [row for row in reader]
            return json.dumps(csv_data)
        except Exception as e:
            logger.error(f"Error reading csv: {e}")
            return f"Error reading csv: {e}"

    def get_columns(self, csv_name: str) -> str:
        """Use this function to get the columns of the csv file `csv_name` without the extension.

        Args:
            csv_name (str): The name of the csv file to get the columns from without the extension.

        Returns:
            str: The columns of the csv file if successful, otherwise returns an error message.
        """
        try:
            if csv_name not in [_csv.stem for _csv in self.csvs]:
                return f"File: {csv_name} not found, please use one of {self.list_csv_files()}"

            logger.info(f"Reading columns from file: {csv_name}")
            file_path = [_csv for _csv in self.csvs if _csv.stem == csv_name][0]

            # Get the columns of the csv file
            with open(str(file_path), newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                columns = reader.fieldnames

            return json.dumps(columns)
        except Exception as e:
            logger.error(f"Error getting columns: {e}")
            return f"Error getting columns: {e}"

    def query_csv_file(self, csv_name: str, sql_query: str) -> str:
        """Use this function to run a SQL query on csv file `csv_name` without the extension.
        The Table name is the name of the csv file without the extension.
        The SQL Query should be a valid DuckDB SQL query.
        Always wrap column names with double quotes if they contain spaces or special characters
        Remember to escape the quotes in th e JSON string (use \")
        Use single quotes for string values

        Args:
            csv_name (str): The name of the csv file to query
            sql_query (str): The SQL Query to run on the csv file.

        Returns:
            str: The query results if successful, otherwise returns an error message.
        """
        try:
            import duckdb

            if csv_name not in [_csv.stem for _csv in self.csvs]:
                return f"File: {csv_name} not found, please use one of {self.list_csv_files()}"

            # Load the csv file into duckdb
            logger.info(f"Loading csv file: {csv_name}")
            file_path = [_csv for _csv in self.csvs if _csv.stem == csv_name][0]

            # Create duckdb connection
            con = self.duckdb_connection
            if not self.duckdb_connection:
                con = duckdb.connect(**(self.duckdb_kwargs or {}))
            if con is None:
                logger.error("Error connecting to DuckDB")
                return "Error connecting to DuckDB, please check the connection."

            # Create a table from the csv file
            con.execute(f"CREATE TABLE {csv_name} AS SELECT * FROM read_csv_auto('{file_path}')")

            # -*- Format the SQL Query
            # Remove backticks
            formatted_sql = sql_query.replace("`", "")
            # If there are multiple statements, only run the first one
            formatted_sql = formatted_sql.split(";")[0]
            # -*- Run the SQL Query
            logger.info(f"Running query: {formatted_sql}")
            query_result = con.sql(formatted_sql)
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

            logger.debug(f"Query result: {result_output}")
            return result_output
        except Exception as e:
            logger.error(f"Error querying csv: {e}")
            return f"Error querying csv: {e}"
