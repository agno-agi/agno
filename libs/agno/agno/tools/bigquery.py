import json
from os import getenv
from typing import Any, Dict, List, Optional
 
from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from google.cloud import bigquery
except ImportError:
    raise ImportError("`bigquery` not installed. Please install it with google-cloud-bigquery")
 
class BQTools(Toolkit):
    def __init__(
        self,
        project: Optional[str] = None,
        location: Optional[str] = None,
        dataset: Optional[str] = None,
        list_tables: Optional[bool] = True,
        describe_table: Optional[bool] = True,
        run_sql_query: Optional[bool] = True,
        credentials: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(name="bq_tools", **kwargs)
        self.project = project or getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or getenv("GOOGLE_CLOUD_LOCATION")  
        self.dataset = dataset
        
        # Initialize the BQ CLient
        self.client = bigquery.Client(project=self.project, credentials=credentials)

        # Register functions in the toolkit
        if list_tables:
            self.register(self.list_tables)
        if describe_table:
            self.register(self.describe_table)
        if run_sql_query:
            self.register(self.run_sql_query)

    def list_tables(self) -> str:
        """Use this function to get a list of table names in the dataset.
 
        Returns:
            str: list of tables in the dataset.
        """
        try:
            log_debug("listing tables in the database")
            tables = self.client.list_tables(self.dataset)
            tables = str([table.table_id for table in tables])
            log_debug(f"table_names: {tables}")
            return json.dumps(tables)
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
            api_response = api_response.to_api_repr()
            desc = str(api_response.get("description", "")) 
            col_names =  str([column["name"] for column in api_response["schema"]["fields"]]) # Columns in a table
            return json.dumps({
                "table_description": desc,
                "columns": col_names
            })
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            return f"Error getting table schema: {e}"
        
    def run_sql_query(self, query: str, limit: Optional[int] = None) -> List[dict]:
        """Use this function to run a BigQuery SQL query and return the result.
 
        Args:
            query (str): The query to run.
            limit (int, optional): The number of rows to return. Defaults to 10. Use `None` to show all results.
        Returns:
            str: Result of the Google BigQuery SQL query.
        Notes:
            - The result may be empty if the query does not return any data.
        """
        try:
            return json.dumps(self._run_sql(sql=query, limit=limit), default=str)
        except Exception as e:
            logger.error(f"Error running query: {e}")
            return f"Error running query: {e}"

    def _run_sql(self, sql: str, limit: Optional[int] = None) -> str:
        """Internal function to run a sql query.
 
        Args:
            sql (str): The sql query to run.
 
        Returns:
            results (str): The result of the query.
        """
        try:
            log_debug(f"Running Google SQL |\n{sql}")
            cleaned_query = (sql.replace("\\n", " ").replace("\n", "").replace("\\", ""))
            if limit:
                cleaned_query = f"{cleaned_query} LIMIT {limit}"
            query_job = self.client.query(cleaned_query)
            results = query_job.result()
            results = str([dict(row) for row in results])
            results = results.replace("\\", "").replace("\n", "")
            return results
        except Exception as e:
            logger.error(f"Error while executing SQL: {e}")
            return []
