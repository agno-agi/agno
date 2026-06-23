import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.databricks.settings import DatabricksSettings
from agno.tools import Toolkit
from agno.tools.databricks_tool_utils import (
    admin_tools_disabled_error,
    build_workspace_client_kwargs,
    resolve_admin_settings,
)
from agno.utils.log import log_error


def _get_workspace_client_cls():
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("`databricks-sdk` not installed. Please install using `pip install databricks-sdk`.") from exc
    return WorkspaceClient


class DatabricksJobsTools(Toolkit):
    """Databricks Jobs tools with approval-gated mutation operations."""

    def __init__(
        self,
        host: Optional[str] = None,
        token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        admin_token: Optional[str] = None,
        admin_client_id: Optional[str] = None,
        admin_client_secret: Optional[str] = None,
        enable_admin_tools: bool = False,
        azure_tenant_id: Optional[str] = None,
        workspace_client: Optional[Any] = None,
        max_results: int = 100,
        enable_list_jobs: bool = True,
        enable_get_job: bool = True,
        enable_list_job_runs: bool = True,
        enable_get_job_run: bool = True,
        enable_run_job_now: bool = True,
        enable_cancel_job_run: bool = True,
        all: bool = False,  # noqa: A002
        **kwargs,
    ):
        self.settings = DatabricksSettings.from_values(
            host=host,
            token=token,
            client_id=client_id,
            client_secret=client_secret,
        )
        self.admin_settings = resolve_admin_settings(
            toolkit_name="DatabricksJobsTools",
            host=host,
            admin_token=admin_token,
            admin_client_id=admin_client_id,
            admin_client_secret=admin_client_secret,
            enable_admin_tools=enable_admin_tools,
            injected_client=workspace_client,
        )
        self.enable_admin_tools = enable_admin_tools
        self.azure_tenant_id = azure_tenant_id or getenv("DATABRICKS_AZURE_TENANT_ID")
        self.max_results = max_results
        self._workspace_client = workspace_client
        self._admin_workspace_client: Optional[Any] = workspace_client if enable_admin_tools else None

        tools: List[Any] = []
        if enable_list_jobs or all:
            tools.append(self.list_jobs)
        if enable_get_job or all:
            tools.append(self.get_job)
        if enable_list_job_runs or all:
            tools.append(self.list_job_runs)
        if enable_get_job_run or all:
            tools.append(self.get_job_run)
        if self.enable_admin_tools and (enable_run_job_now or all):
            tools.append(self.run_job_now)
        if self.enable_admin_tools and (enable_cancel_job_run or all):
            tools.append(self.cancel_job_run)

        requires_confirmation_tools: List[str] = []
        if self.enable_admin_tools:
            if enable_run_job_now or all:
                requires_confirmation_tools.append("run_job_now")
            if enable_cancel_job_run or all:
                requires_confirmation_tools.append("cancel_job_run")

        instructions = kwargs.pop(
            "instructions",
            "Use these tools for Databricks Jobs inspection. Triggering or cancelling runs is only available when explicitly enabled with dedicated admin credentials and still requires approval.",
        )
        add_instructions = kwargs.pop("add_instructions", True)

        super().__init__(
            name="databricks_jobs_tools",
            tools=tools,
            instructions=instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=requires_confirmation_tools,
            **kwargs,
        )

    @property
    def client(self) -> Any:
        if self._workspace_client is None:
            client_cls = _get_workspace_client_cls()
            self._workspace_client = client_cls(
                **build_workspace_client_kwargs(self.settings, azure_tenant_id=self.azure_tenant_id)
            )
        return self._workspace_client

    @property
    def admin_client(self) -> Any:
        if not self.enable_admin_tools:
            raise RuntimeError(admin_tools_disabled_error("DatabricksJobsTools", "running Databricks jobs"))

        if self._admin_workspace_client is None:
            client_cls = _get_workspace_client_cls()
            if self.admin_settings is None:
                raise RuntimeError(admin_tools_disabled_error("DatabricksJobsTools", "running Databricks jobs"))
            self._admin_workspace_client = client_cls(
                **build_workspace_client_kwargs(self.admin_settings, azure_tenant_id=self.azure_tenant_id)
            )
        return self._admin_workspace_client

    def list_jobs(self, name_contains: Optional[str] = None, limit: Optional[int] = None) -> str:
        """Use this function to list Databricks jobs."""
        try:
            jobs_iter = self.client.jobs.list(name=name_contains, expand_tasks=False, limit=limit or self.max_results)
            return json.dumps(self._serialize_items(jobs_iter, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks jobs: {str(e)}")
            return "Error listing Databricks jobs: An internal error occurred. Check server logs for details."

    def get_job(self, job_id: int) -> str:
        """Use this function to fetch Databricks job metadata by job id."""
        try:
            job = self.client.jobs.get(job_id=job_id)
            return json.dumps(self._serialize_item(job), default=str)
        except Exception as e:
            log_error(f"Error getting Databricks job: {str(e)}")
            return "Error getting Databricks job: An internal error occurred. Check server logs for details."

    def list_job_runs(
        self,
        job_id: Optional[int] = None,
        active_only: bool = False,
        completed_only: bool = False,
        limit: Optional[int] = None,
    ) -> str:
        """Use this function to list Databricks job runs."""
        try:
            runs_iter = self.client.jobs.list_runs(
                job_id=job_id,
                active_only=active_only,
                completed_only=completed_only,
                limit=limit or self.max_results,
            )
            return json.dumps(self._serialize_items(runs_iter, limit), default=str)
        except Exception as e:
            log_error(f"Error listing Databricks job runs: {str(e)}")
            return "Error listing Databricks job runs: An internal error occurred. Check server logs for details."

    def get_job_run(self, run_id: int) -> str:
        """Use this function to fetch a Databricks run by run id."""
        try:
            run = self.client.jobs.get_run(run_id=run_id)
            return json.dumps(self._serialize_item(run), default=str)
        except Exception as e:
            log_error(f"Error getting Databricks job run: {str(e)}")
            return "Error getting Databricks job run: An internal error occurred. Check server logs for details."

    def run_job_now(
        self,
        job_id: int,
        notebook_params: Optional[Dict[str, str]] = None,
        job_parameters: Optional[Dict[str, str]] = None,
        python_params: Optional[List[str]] = None,
        only_tasks: Optional[List[str]] = None,
    ) -> str:
        """Use this function to trigger a Databricks job run immediately."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksJobsTools", "running Databricks jobs")
        try:
            waiter = self.admin_client.jobs.run_now(
                job_id=job_id,
                notebook_params=notebook_params,
                job_parameters=job_parameters,
                python_params=python_params,
                only=only_tasks,
            )
            response = getattr(waiter, "response", waiter)
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error triggering Databricks job: {str(e)}")
            return "Error triggering Databricks job: An internal error occurred. Check server logs for details."

    def cancel_job_run(self, run_id: int) -> str:
        """Use this function to cancel an active Databricks job run."""
        if not self.enable_admin_tools:
            return admin_tools_disabled_error("DatabricksJobsTools", "cancelling Databricks job runs")
        try:
            response = self.admin_client.jobs.cancel_run(run_id=run_id)
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error cancelling Databricks job run: {str(e)}")
            return "Error cancelling Databricks job run: An internal error occurred. Check server logs for details."

    def _serialize_items(self, items, limit=None) -> List[Dict[str, Any]]:
        from agno.tools.databricks_tool_utils import serialize_sdk_items
        return serialize_sdk_items(items, limit, self.max_results)

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        from agno.tools.databricks_tool_utils import serialize_sdk_item
        return serialize_sdk_item(item)
