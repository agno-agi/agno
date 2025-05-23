import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from google.cloud import bigquery
except ImportError:
    raise ImportError("`bigquery` not installed. Please install using `pip install google-cloud-bigquery`")


class GoogleBigQueryTools(Toolkit):
    def __init__(
        self,
        dataset: str,
        project: Optional[str] = None,
        location: Optional[str] = None,
        list_tables: Optional[bool] = True,
        describe_table: Optional[bool] = True,
        run_sql_query: Optional[bool] = True,
        credentials: Optional[Any] = None,
        **kwargs,
    ):
        self.project = project or getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or getenv("GOOGLE_CLOUD_LOCATION")

        if not self.project:
            raise ValueError("project is required")
        if not self.location:
            raise ValueError("location is required")

        self.dataset = dataset

        # Initialize the BQ CLient
        self.client = bigquery.Client(project=self.project, credentials=credentials)

        tools: List[Any] = []
        if list_tables:
            tools.append(self.list_tables)
        if describe_table:
            tools.append(self.describe_table)
        if run_sql_query:
            tools.append(self.run_sql_query)

        super().__init__(name="google_bigquery_tools", tools=tools, **kwargs)

    def list_tables(self) -> str:
        """Use this function to get a list of table names in the dataset.
        Returns:
            str: list of tables in the dataset.
        """
        try:
            log_debug("listing tables in the database")
            tables = self.client.list_tables(self.dataset)
            tables_str = str([table.table_id for table in tables])
            log_debug(f"table_names: {tables_str}")
            return tables_str
        except Exception as e:
            logger.error(f"Error getting tables: {e}")
            return f"Error getting tables: {e}"

    def describe_table(self, table_id: str) -> str:
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
            desc = str(table_api_repr.get("description", ""))
            col_names = str([column["name"] for column in table_api_repr["schema"]["fields"]])  # Columns in a table
            result = json.dumps({"table_description": desc, "columns": col_names})
            return result
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            return f"Error getting table schema: {e}"

    def run_sql_query(self, query: str) -> str:
        """Use this function to run a BigQuery SQL query and return the result.
        Args:
            query (str): The query to run.
        Returns:
            str: Result of the Google BigQuery SQL query.
        Notes:
            - The result may be empty if the query does not return any data.
        """
        try:
            return json.dumps(self._run_sql(sql=query), default=str)
        except Exception as e:
            logger.error(f"Error running query: {e}")
            return f"Error running query: {e}"

    def _run_sql(self, sql: str) -> str:
        """Internal function to run a sql query.
        Args:
            sql (str): The sql query to run.
        Returns:
            results (str): The result of the query.
        """
        try:
            log_debug(f"Running Google SQL |\n{sql}")
            cleaned_query = sql.replace("\\n", " ").replace("\n", "").replace("\\", "")
            query_job = self.client.query(cleaned_query)
            results = query_job.result()
            results_str = str([dict(row) for row in results])
            return results_str.replace("\\", "").replace("\n", "")
        except Exception as e:
            logger.error(f"Error while executing SQL: {e}")
            return ""
