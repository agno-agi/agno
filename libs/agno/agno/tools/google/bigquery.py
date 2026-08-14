import json
import warnings
from os import getenv
from typing import Any, Callable, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    from google.cloud import bigquery
except ImportError:
    raise ImportError("`bigquery` not installed. Please install using `pip install google-cloud-bigquery`")


def _clean_sql(sql: str) -> str:
    """Clean SQL query by normalizing whitespace while preserving token boundaries.

    Replaces newlines with spaces (not empty strings) to prevent line comments
    from swallowing subsequent SQL statements.
    """
    return sql.replace("\\n", " ").replace("\n", " ")


class GoogleBigQueryTools(Toolkit):
    """Toolkit for interacting with Google BigQuery.

    Args:
        dataset: BigQuery dataset name.
        project: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT env var.
        location: GCP location. Falls back to GOOGLE_CLOUD_LOCATION env var.
        credentials: Pre-fetched credentials object.
        list_tables: Enable list_tables tool. Defaults to True.
        describe_table: Enable describe_table tool. Defaults to True.
        run_sql_query: Enable run_sql_query tool. Defaults to False (executes arbitrary SQL).
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        dataset: str,
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials: Optional[Any] = None,
        list_tables: bool = True,
        describe_table: bool = True,
        run_sql_query: bool = False,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat for old param names
        if "enable_list_tables" in kwargs:
            warnings.warn("enable_list_tables is deprecated, use list_tables", DeprecationWarning, stacklevel=2)
            list_tables = kwargs.pop("enable_list_tables")
        if "enable_describe_table" in kwargs:
            warnings.warn("enable_describe_table is deprecated, use describe_table", DeprecationWarning, stacklevel=2)
            describe_table = kwargs.pop("enable_describe_table")
        if "enable_run_sql_query" in kwargs:
            warnings.warn("enable_run_sql_query is deprecated, use run_sql_query", DeprecationWarning, stacklevel=2)
            run_sql_query = kwargs.pop("enable_run_sql_query")

        self.project = project or getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or getenv("GOOGLE_CLOUD_LOCATION")

        if not self.project:
            raise ValueError("project is required")
        if not self.location:
            raise ValueError("location is required")

        self.dataset = dataset

        # Initialize the BQ CLient
        self.client = bigquery.Client(project=self.project, credentials=credentials)

        tools: List[Callable] = []
        if all or list_tables:
            tools.append(self.list_bigquery_tables)
        if all or describe_table:
            tools.append(self.describe_bigquery_table)
        if all or run_sql_query:
            tools.append(self.run_bigquery_sql)

        super().__init__(name="google_bigquery_tools", tools=tools, **kwargs)

    def list_bigquery_tables(self) -> str:
        """Use this function to get a list of table names in the dataset.
        Returns:
            str: list of tables in the dataset.
        """
        try:
            log_debug("listing tables in the database")
            tables = self.client.list_tables(self.dataset)
            table_names = [table.table_id for table in tables]
            log_debug(f"table_names: {table_names}")
            return json.dumps({"tables": table_names})
        except Exception as e:
            log_error(f"Error getting tables: {e}")
            return json.dumps({"error": f"Error getting tables: {e}"})

    def describe_bigquery_table(self, table_id: str) -> str:
        """Use this function to describe a table.
        Args:
            table_name (str): The name of the table to get the schema for.
        Returns:
            str: schema of a table
        """
        try:
            table_id = f"{self.project}.{self.dataset}.{table_id}"
            log_debug(f"Describing table: {table_id}")
            api_response = self.client.get_table(table_id)
            table_api_repr = api_response.to_api_repr()
            desc = table_api_repr.get("description", "")
            columns = [column["name"] for column in table_api_repr["schema"]["fields"]]
            return json.dumps({"table_description": desc, "columns": columns})
        except Exception as e:
            log_error(f"Error getting table schema: {e}")
            return json.dumps({"error": f"Error getting table schema: {e}"})

    def run_bigquery_sql(self, query: str) -> str:
        """Use this function to run a BigQuery SQL query and return the result.
        Args:
            query (str): The query to run.
        Returns:
            str: Result of the Google BigQuery SQL query.
        Notes:
            - The result may be empty if the query does not return any data.
        """
        try:
            log_debug(f"Running Google SQL |\n{query}")
            cleaned_query = _clean_sql(query)
            job_config = bigquery.QueryJobConfig(default_dataset=f"{self.project}.{self.dataset}")
            query_job = self.client.query(cleaned_query, job_config)
            results = query_job.result()
            rows = [dict(row) for row in results]
            return json.dumps({"rows": rows}, default=str)
        except Exception as e:
            log_error(f"Error running query: {e}")
            return json.dumps({"error": f"Error running query: {e}"})
