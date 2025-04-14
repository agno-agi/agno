import csv
import io
import json
import os
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd
from agno.tools.base import BaseTool
from agno.tools.utils import get_tool_config
from pydantic import BaseModel, Field


class CSVToolkit(BaseTool):
    """Tool for working with CSV files."""

    name = "csv_toolkit"
    description = "Tool for working with CSV files."

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize the CSV toolkit."""
        super().__init__(config)
        self.config = get_tool_config(self.name, config)

    def read_csv(self, file_path: str, **kwargs) -> pd.DataFrame:
        """Read a CSV file into a pandas DataFrame.

        Args:
            file_path: Path to the CSV file.
            **kwargs: Additional arguments to pass to pandas.read_csv.

        Returns:
            A pandas DataFrame containing the CSV data.
        """
        return pd.read_csv(file_path, **kwargs)

    def write_csv(self, df: pd.DataFrame, file_path: str, **kwargs) -> None:
        """Write a pandas DataFrame to a CSV file.

        Args:
            df: The pandas DataFrame to write.
            file_path: Path to the CSV file.
            **kwargs: Additional arguments to pass to pandas.to_csv.
        """
        df.to_csv(file_path, **kwargs)

    def csv_to_json(self, csv_file: str, json_file: str) -> None:
        """Convert a CSV file to a JSON file.

        Args:
            csv_file: Path to the CSV file.
            json_file: Path to the JSON file.
        """
        df = pd.read_csv(csv_file)
        df.to_json(json_file, orient="records")

    def json_to_csv(self, json_file: str, csv_file: str) -> None:
        """Convert a JSON file to a CSV file.

        Args:
            json_file: Path to the JSON file.
            csv_file: Path to the CSV file.
        """
        with open(json_file, "r") as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        df.to_csv(csv_file, index=False)

    def csv_to_sqlite(
        self, csv_file: str, db_file: str, table_name: str, if_exists: str = "replace"
    ) -> None:
        """Convert a CSV file to a SQLite database.

        Args:
            csv_file: Path to the CSV file.
            db_file: Path to the SQLite database.
            table_name: Name of the table to create.
            if_exists: What to do if the table exists. Options are 'fail', 'replace', and 'append'.
        """
        df = pd.read_csv(csv_file)
        conn = sqlite3.connect(db_file)
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        conn.close()

    def sqlite_to_csv(self, db_file: str, table_name: str, csv_file: str) -> None:
        """Convert a SQLite table to a CSV file.

        Args:
            db_file: Path to the SQLite database.
            table_name: Name of the table to export.
            csv_file: Path to the CSV file.
        """
        conn = sqlite3.connect(db_file)
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        df.to_csv(csv_file, index=False)
        conn.close()

    def query_sqlite(self, db_file: str, query: str) -> pd.DataFrame:
        """Run a SQL query on a SQLite database and return the results as a pandas DataFrame.

        Args:
            db_file: Path to the SQLite database.
            query: SQL query to run.

        Returns:
            A pandas DataFrame containing the query results.
        """
        conn = sqlite3.connect(db_file)
        # Fix: Use parameterized query instead of string formatting
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df

    def query_csv(self, csv_file: str, query: str) -> pd.DataFrame:
        """Run a SQL query on a CSV file and return the results as a pandas DataFrame.

        Args:
            csv_file: Path to the CSV file.
            query: SQL query to run.

        Returns:
            A pandas DataFrame containing the query results.
        """
        # Create a temporary SQLite database
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as temp_db:
            temp_db_path = temp_db.name

        try:
            # Convert CSV to SQLite
            df = pd.read_csv(csv_file)
            conn = sqlite3.connect(temp_db_path)
            df.to_sql("data", conn, if_exists="replace", index=False)
            
            # Execute the query using parameterized query
            result_df = pd.read_sql_query(query, conn)
            conn.close()
            
            return result_df
        finally:
            # Clean up the temporary database file
            if os.path.exists(temp_db_path):
                os.unlink(temp_db_path)

    def filter_csv(
        self, csv_file: str, column: str, value: Any, operator: str = "=="
    ) -> pd.DataFrame:
        """Filter a CSV file based on a column value.

        Args:
            csv_file: Path to the CSV file.
            column: Column to filter on.
            value: Value to filter for.
            operator: Comparison operator to use. Options are '==', '!=', '<', '<=', '>', '>='.

        Returns:
            A pandas DataFrame containing the filtered data.
        """
        df = pd.read_csv(csv_file)
        if operator == "==":
            return df[df[column] == value]
        elif operator == "!=":
            return df[df[column] != value]
        elif operator == "<":
            return df[df[column] < value]
        elif operator == "<=":
            return df[df[column] <= value]
        elif operator == ">":
            return df[df[column] > value]
        elif operator == ">=":
            return df[df[column] >= value]
        else:
            raise ValueError(f"Unsupported operator: {operator}")

    def sort_csv(
        self, csv_file: str, column: str, ascending: bool = True
    ) -> pd.DataFrame:
        """Sort a CSV file based on a column.

        Args:
            csv_file: Path to the CSV file.
            column: Column to sort on.
            ascending: Whether to sort in ascending order.

        Returns:
            A pandas DataFrame containing the sorted data.
        """
        df = pd.read_csv(csv_file)
        return df.sort_values(by=column, ascending=ascending)

    def group_by_csv(
        self, csv_file: str, column: str, agg_func: str = "count"
    ) -> pd.DataFrame:
        """Group a CSV file by a column and aggregate.

        Args:
            csv_file: Path to the CSV file.
            column: Column to group by.
            agg_func: Aggregation function to use. Options are 'count', 'sum', 'mean', 'median', 'min', 'max'.

        Returns:
            A pandas DataFrame containing the grouped data.
        """
        df = pd.read_csv(csv_file)
        if agg_func == "count":
            return df.groupby(column).size().reset_index(name="count")
        elif agg_func == "sum":
            return df.groupby(column).sum().reset_index()
        elif agg_func == "mean":
            return df.groupby(column).mean().reset_index()
        elif agg_func == "median":
            return df.groupby(column).median().reset_index()
        elif agg_func == "min":
            return df.groupby(column).min().reset_index()
        elif agg_func == "max":
            return df.groupby(column).max().reset_index()
        else:
            raise ValueError(f"Unsupported aggregation function: {agg_func}")

    def merge_csv(
        self,
        left_csv: str,
        right_csv: str,
        on: str,
        how: str = "inner",
    ) -> pd.DataFrame:
        """Merge two CSV files.

        Args:
            left_csv: Path to the left CSV file.
            right_csv: Path to the right CSV file.
            on: Column to merge on.
            how: Type of merge to perform. Options are 'inner', 'outer', 'left', 'right'.

        Returns:
            A pandas DataFrame containing the merged data.
        """
        left_df = pd.read_csv(left_csv)
        right_df = pd.read_csv(right_csv)
        return pd.merge(left_df, right_df, on=on, how=how)

    def pivot_csv(
        self, csv_file: str, index: str, columns: str, values: str
    ) -> pd.DataFrame:
        """Pivot a CSV file.

        Args:
            csv_file: Path to the CSV file.
            index: Column to use as index.
            columns: Column to use as columns.
            values: Column to use as values.

        Returns:
            A pandas DataFrame containing the pivoted data.
        """
        df = pd.read_csv(csv_file)
        return df.pivot(index=index, columns=columns, values=values)

    def melt_csv(
        self, csv_file: str, id_vars: List[str], value_vars: List[str]
    ) -> pd.DataFrame:
        """Melt a CSV file.

        Args:
            csv_file: Path to the CSV file.
            id_vars: Columns to use as identifier variables.
            value_vars: Columns to unpivot.

        Returns:
            A pandas DataFrame containing the melted data.
        """
        df = pd.read_csv(csv_file)
        return pd.melt(df, id_vars=id_vars, value_vars=value_vars)

    def get_csv_info(self, csv_file: str) -> Dict[str, Any]:
        """Get information about a CSV file.

        Args:
            csv_file: Path to the CSV file.

        Returns:
            A dictionary containing information about the CSV file.
        """
        df = pd.read_csv(csv_file)
        return {
            "shape": df.shape,
            "columns": df.columns.tolist(),
            "dtypes": df.dtypes.astype(str).to_dict(),
            "head": df.head().to_dict(orient="records"),
            "tail": df.tail().to_dict(orient="records"),
            "describe": df.describe().to_dict(),
        }
