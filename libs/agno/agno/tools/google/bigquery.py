import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.tools._security import assert_read_only_sql
from agno.utils.log import log_debug, logger

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
    """Query Google BigQuery datasets.

    Security notes (hardened build):

    * :meth:`run_sql_query` refuses any statement other than a single
      ``SELECT`` / ``WITH`` via :func:`assert_read_only_sql`. A
      ``dry_run`` flag is available to estimate cost without running
      the query or materialising results.
    * The toolkit honours the dataset scoping set at construction
      time; queries run with ``default_dataset`` pointed at
      ``project.dataset``.

    Args:
        dataset: BigQuery dataset name.
        project: GCP project. Defaults to
            ``$GOOGLE_CLOUD_PROJECT``.
        location: BigQuery location. Defaults to
            ``$GOOGLE_CLOUD_LOCATION``.
        credentials: Optional ``google.auth.credentials.Credentials``
            instance. Falls back to application-default credentials.
        list_tables: Register :meth:`list_tables`.
        describe_table: Register :meth:`describe_table`.
        run_sql_query: Register :meth:`run_sql_query`.
        enable_list_tables: Deprecated alias for ``list_tables``.
        enable_describe_table: Deprecated alias for ``describe_table``.
        enable_run_sql_query: Deprecated alias for ``run_sql_query``.
    """

    def __init__(
        self,
        dataset: str,
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials: Optional[Any] = None,
        list_tables: bool = True,
        describe_table: bool = True,
        run_sql_query: bool = True,
        # Backward compat aliases (deprecated)
        enable_list_tables: Optional[bool] = None,
        enable_describe_table: Optional[bool] = None,
        enable_run_sql_query: Optional[bool] = None,
        all: bool = False,
        **kwargs,
    ):
        self.project = project or getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or getenv("GOOGLE_CLOUD_LOCATION")

        if not self.project:
            raise ValueError("project is required")
        if not self.location:
            raise ValueError("location is required")

        self.dataset = dataset

        # Resolve deprecated aliases: explicit deprecated flag overrides new flag
        _list_tables = enable_list_tables if enable_list_tables is not None else list_tables
        _describe_table = enable_describe_table if enable_describe_table is not None else describe_table
        _run_sql_query = enable_run_sql_query if enable_run_sql_query is not None else run_sql_query

        # Initialize the BQ CLient
        self.client = bigquery.Client(project=self.project, credentials=credentials)

        tools: List[Any] = []
        if all or _list_tables:
            tools.append(self.list_tables)
        if all or _describe_table:
            tools.append(self.describe_table)
        if all or _run_sql_query:
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
            logger.exception("Error getting tables")
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
            logger.exception("Error getting table schema")
            return f"Error getting table schema: {e}"

    def run_sql_query(self, query: str, dry_run: bool = False) -> str:
        """Use this function to run a BigQuery SQL query and return the result.
        Args:
            query (str): The query to run.
            dry_run (bool): If True, run as a BigQuery dry run (no rows,
                no cost) to validate the query and return byte estimate.
        Returns:
            str: Result of the Google BigQuery SQL query.
        Notes:
            - The result may be empty if the query does not return any data.
        """
        try:
            assert_read_only_sql(query)
        except ValueError as e:
            return f"Error: {e}"
        try:
            return json.dumps(self._run_sql(sql=query, dry_run=dry_run), default=str)
        except Exception as e:
            logger.exception("Error running query")
            return f"Error running query: {e}"

    def _run_sql(self, sql: str, dry_run: bool = False) -> str:
        """Internal function to run a sql query.
        Args:
            sql (str): The sql query to run.
        Returns:
            results (str): The result of the query.
        """
        try:
            log_debug(f"Running Google SQL |\n{sql}")
            cleaned_query = _clean_sql(sql)
            job_config = bigquery.QueryJobConfig(
                default_dataset=f"{self.project}.{self.dataset}",
                dry_run=dry_run,
                use_query_cache=not dry_run,
            )
            query_job = self.client.query(cleaned_query, job_config)
            if dry_run:
                return json.dumps(
                    {
                        "dry_run": True,
                        "total_bytes_processed": query_job.total_bytes_processed,
                    }
                )
            results = query_job.result()
            results_str = str([dict(row) for row in results])
            return results_str.replace("\n", " ")
        except Exception:
            logger.exception("Error while executing SQL")
            return ""
