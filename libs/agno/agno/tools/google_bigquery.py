import hashlib
import json
from os import getenv
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar

from agno.exceptions import RetryAgentRun, StopAgentRun
from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

try:
    from google.cloud import bigquery
    from google.api_core import exceptions as gexc
except ImportError as e:
    raise ImportError(
        "`google-cloud-bigquery` not installed. Please install using `pip install google-cloud-bigquery`"
    ) from e

T = TypeVar("T")

class GoogleBigQueryTools(Toolkit):
    """
    BigQuery Toolkit with:
      - dataset/table identifier normalization
      - runtime-driven retry signaling via RetryAgentRun(stop_execution=False)
      - configurable JSON serialization (ensure_ascii)
      - consistent JSON return shapes across methods
      - per-operation/per-key retry budget enforcement inside the tool
    """

    def __init__(
        self,
        dataset: str,
        project: Optional[str] = None,
        location: Optional[str] = None,
        credentials: Optional[Any] = None,
        enable_list_tables: bool = True,
        enable_describe_table: bool = True,
        enable_run_sql_query: bool = True,
        enable_all: bool = False,
        ensure_ascii: bool = False,
        max_retries: int = 3,
        max_results: int = 3000,
        **kwargs,
    ):
        self.project = project or getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location or getenv("GOOGLE_CLOUD_LOCATION")

        if not self.project:
            raise ValueError("project is required")
        if not self.location:
            raise ValueError("location is required")
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")
        if max_results < 1:
            raise ValueError("max_results must be >= 1")

        self.max_retries = int(max_retries)
        self.max_results = int(max_results)
        self.ensure_ascii = bool(ensure_ascii)

        # (action, key) -> failure count (used to decide Retry vs Stop)
        self._fail_counts: Dict[Tuple[str, str], int] = {}

        # BigQuery client
        self.client = bigquery.Client(project=self.project, credentials=credentials)

        # Dataset normalization
        self.dataset_project, self.dataset_id = self._parse_dataset_identifier(
            dataset=dataset,
            default_project=self.project,
        )

        tools = []
        if enable_all or enable_list_tables:
            tools.append(self.list_tables)
        if enable_all or enable_describe_table:
            tools.append(self.describe_table)
        if enable_all or enable_run_sql_query:
            tools.append(self.run_sql_query)

        super().__init__(name="google_bigquery_tools", tools=tools, **kwargs)

    # -------------------------
    # Public config
    # -------------------------
    def set_ensure_ascii(self, ensure_ascii: bool) -> None:
        """Toggle JSON ensure_ascii at runtime."""
        self.ensure_ascii = bool(ensure_ascii)

    # -------------------------
    # Internal helpers
    # -------------------------
    def _json_dumps(self, payload: Any, *, ensure_ascii: Optional[bool] = None, **kwargs) -> str:
        ascii_flag = self.ensure_ascii if ensure_ascii is None else bool(ensure_ascii)
        return json.dumps(payload, ensure_ascii=ascii_flag, **kwargs)

    @staticmethod
    def _parse_dataset_identifier(dataset: str, default_project: str) -> tuple[str, str]:
        """
        Accept:
          - dataset
          - project.dataset
          - project:dataset
        Return: (project, dataset_id)
        """
        ds = (dataset or "").strip()
        if not ds:
            raise ValueError("dataset is required.")

        if ":" in ds and "." not in ds:
            proj, ds_id = ds.split(":", 1)
            proj, ds_id = proj.strip(), ds_id.strip()
            if not proj or not ds_id:
                raise ValueError(f"Invalid dataset identifier: {dataset}")
            return proj, ds_id

        if ds.count(".") == 1:
            proj, ds_id = ds.split(".", 1)
            proj, ds_id = proj.strip(), ds_id.strip()
            if not proj or not ds_id:
                raise ValueError(f"Invalid dataset identifier: {dataset}")
            return proj, ds_id

        return default_project, ds

    def _qualify_table_identifier(self, table_id: str) -> str:
        """
        Accept:
          - table
          - dataset.table
          - project.dataset.table
          - project:dataset.table
        Return: "project.dataset.table"
        """
        tid = (table_id or "").strip()
        if not tid:
            raise ValueError("table_id is required")

        if ":" in tid:
            proj, rest = tid.split(":", 1)
            proj, rest = proj.strip(), rest.strip()
            if rest.count(".") != 1:
                raise ValueError(f"Invalid table identifier: {table_id}")
            ds_id, tbl = rest.split(".", 1)
            ds_id, tbl = ds_id.strip(), tbl.strip()
            if not proj or not ds_id or not tbl:
                raise ValueError(f"Invalid table identifier: {table_id}")
            return f"{proj}.{ds_id}.{tbl}"

        parts = [p.strip() for p in tid.split(".") if p.strip()]
        if len(parts) == 1:
            return f"{self.dataset_project}.{self.dataset_id}.{parts[0]}"
        if len(parts) == 2:
            return f"{self.dataset_project}.{parts[0]}.{parts[1]}"
        if len(parts) == 3:
            return f"{parts[0]}.{parts[1]}.{parts[2]}"

        raise ValueError(f"Invalid table identifier: {table_id}")

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _should_stop_immediately(e: Exception) -> bool:
        """
        Heuristic:
          - Stop immediately for deterministic/user-fixable errors.
          - Retry for transient/service errors.
        """
        # Deterministic / user-fixable
        if isinstance(e, (gexc.BadRequest, gexc.Forbidden, gexc.NotFound)):
            return True

        # Quota / transient / backend: allow retry budget
        if isinstance(
            e,
            (
                gexc.TooManyRequests,
                gexc.ServiceUnavailable,
                gexc.InternalServerError,
                gexc.GatewayTimeout,
            ),
        ):
            return False

        # Default: treat as retryable until budget is exhausted
        return False

    def _with_retry_budget(
        self,
        action: str,
        key: str,
        fn: Callable[[], T],
    ) -> T:
        """
        Single-attempt executor that:
          - increments per-(action,key) failure count on exception
          - raises RetryAgentRun to let the runtime re-invoke the tool
          - raises StopAgentRun once budget exceeded or for deterministic errors
        """
        k = (action, key)
        try:
            out = fn()
            self._fail_counts.pop(k, None)  # reset on success
            return out
        except (RetryAgentRun, StopAgentRun):
            raise
        except Exception as e:
            cnt = self._fail_counts.get(k, 0) + 1
            self._fail_counts[k] = cnt

            logger.exception(f"Error during {action} (attempt {cnt}/{self.max_retries})")

            # Immediate stop for deterministic errors
            if self._should_stop_immediately(e):
                raise StopAgentRun(f"BigQuery {action} failed (non-retryable): {e}") from e

            # Budget exhausted
            if cnt >= self.max_retries:
                raise StopAgentRun(f"BigQuery {action} failed after {cnt} attempts: {e}") from e

            # Let runtime retry this tool call
            raise RetryAgentRun(
                e,
                agent_message=(
                    f"BigQuery {action} failed (attempt {cnt}/{self.max_retries}): {e}. "
                    "Validate identifiers/permissions/location and retry."
                ),
            ) from e

    # -------------------------
    # Tools
    # -------------------------
    def list_tables(self, ensure_ascii: Optional[bool] = None) -> str:
        """
        List tables in the configured dataset.
        Returns JSON:
          {"ok": true, "dataset": "project.dataset", "tables": ["t1", "t2", ...]}
        """
        dataset_fq = f"{self.dataset_project}.{self.dataset_id}"

        def _do() -> str:
            log_debug(f"listing tables in dataset: {dataset_fq}")
            tables = self.client.list_tables(dataset_fq)
            table_names = [t.table_id for t in tables]
            return self._json_dumps(
                {"ok": True, "dataset": dataset_fq, "tables": table_names},
                ensure_ascii=ensure_ascii,
            )

        return self._with_retry_budget("list_tables", key=dataset_fq, fn=_do)

    def describe_table(self, table_id: str, ensure_ascii: Optional[bool] = None) -> str:
        """
        Describe a table schema.
        Returns JSON:
          {
            "ok": true,
            "table_id": "project.dataset.table",
            "table_description": "...",
            "columns": ["A", "B", ...],
            "column_descriptions": {"A": "...", ...},
            "column_details": [
              {"name": "...", "type": "...", "mode": "...", "description": "...", "fields": [...]?},
              ...
            ]
          }
        """
        fq_table = self._qualify_table_identifier(table_id)

        def _do() -> str:
            log_debug(f"describing table: {fq_table}")

            api_response = self.client.get_table(fq_table)
            table_api_repr = api_response.to_api_repr()

            desc = str(table_api_repr.get("description", "") or "")
            fields = table_api_repr.get("schema", {}).get("fields", []) or []

            def normalize_field(field: dict) -> dict:
                out = {
                    "name": field.get("name", "") or "",
                    "type": field.get("type", "") or "",
                    "mode": field.get("mode", "") or "",
                    "description": field.get("description", "") or "",
                }
                nested = field.get("fields")
                if isinstance(nested, list) and nested:
                    out["fields"] = [normalize_field(f) for f in nested]
                return out

            columns = [f.get("name", "") for f in fields if f.get("name")]
            column_details = [normalize_field(f) for f in fields]
            column_descriptions = {
                f.get("name", ""): (f.get("description", "") or "")
                for f in fields
                if f.get("name")
            }

            payload = {
                "ok": True,
                "table_id": fq_table,
                "table_description": desc,
                "columns": columns,
                "column_descriptions": column_descriptions,
                "column_details": column_details,
            }
            return self._json_dumps(payload, ensure_ascii=ensure_ascii)

        return self._with_retry_budget("describe_table", key=fq_table, fn=_do)

    def run_sql_query(self, query: str, ensure_ascii: Optional[bool] = None) -> str:
        """
        Run a SQL query in BigQuery.
        Returns JSON:
          {"ok": true, "rows": [ {...}, ... ]}
        """
        # Key by normalized query text to enforce budget per logical query
        cleaned_query = (
            (query or "")
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
            .strip()
        )
        key = self._fingerprint(cleaned_query)

        def _do() -> str:
            rows = self._run_sql(cleaned_sql=cleaned_query)
            return self._json_dumps(
                {"ok": True, "rows": rows},
                ensure_ascii=ensure_ascii,
                default=str,
            )

        return self._with_retry_budget("run_sql_query", key=key, fn=_do)

    def _run_sql(self, cleaned_sql: str) -> list[dict]:
        """
        Internal SQL execution. Raises exceptions; caller wraps with _with_retry_budget().
        """
        log_debug(f"Running Google SQL |\n{cleaned_sql}")

        job_config = bigquery.QueryJobConfig(
            default_dataset=f"{self.dataset_project}.{self.dataset_id}",
            use_legacy_sql=False,
        )

        query_job = self.client.query(
            cleaned_sql,
            job_config=job_config,
            location=self.location,
        )
        results = query_job.result(max_results=self.max_results)
        
        return [dict(row) for row in results]
