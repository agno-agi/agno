import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.tools.databricks_tool_utils import build_workspace_client_kwargs, resolve_admin_settings
from agno.utils.log import log_error


def _get_jobs_sdk():
    try:
        from databricks.sdk import WorkspaceClient  # type: ignore[import-not-found]
        from databricks.sdk.service import jobs as jobs_service  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError("`databricks-sdk` not installed. Please install using `pip install databricks-sdk`.") from exc
    return WorkspaceClient, jobs_service


class DatabricksJobsAdminTools(Toolkit):
    """Administrative Databricks Jobs tools for create/update/delete and one-time submissions."""

    def __init__(
        self,
        host: Optional[str] = None,
        admin_token: Optional[str] = None,
        admin_client_id: Optional[str] = None,
        admin_client_secret: Optional[str] = None,
        enable_admin_tools: bool = False,
        azure_tenant_id: Optional[str] = None,
        workspace_client: Optional[Any] = None,
        **kwargs,
    ):
        if not enable_admin_tools:
            raise ValueError(
                "DatabricksJobsAdminTools requires enable_admin_tools=True to expose Databricks admin operations."
            )

        self.settings = resolve_admin_settings(
            toolkit_name="DatabricksJobsAdminTools",
            host=host,
            admin_token=admin_token,
            admin_client_id=admin_client_id,
            admin_client_secret=admin_client_secret,
            enable_admin_tools=enable_admin_tools,
            injected_client=workspace_client,
        )
        if self.settings is None:
            raise ValueError(
                "DatabricksJobsAdminTools requires enable_admin_tools=True to expose Databricks admin operations."
            )
        self.azure_tenant_id = azure_tenant_id or getenv("DATABRICKS_AZURE_TENANT_ID")
        self._workspace_client = workspace_client

        tools: List[Any] = [
            self.create_job,
            self.update_job,
            self.delete_job,
            self.submit_one_time_run,
        ]

        instructions = kwargs.pop(
            "instructions",
            "Use these tools for Databricks job administration only when explicitly enabled with dedicated admin credentials. All operations here are state-changing and require approval.",
        )
        add_instructions = kwargs.pop("add_instructions", True)

        super().__init__(
            name="databricks_jobs_admin_tools",
            tools=tools,
            instructions=instructions,
            add_instructions=add_instructions,
            requires_confirmation_tools=["create_job", "update_job", "delete_job", "submit_one_time_run"],
            **kwargs,
        )

    @property
    def client(self) -> Any:
        if self._workspace_client is None:
            workspace_client_cls, _ = _get_jobs_sdk()
            if self.settings is None:
                raise RuntimeError(
                    "DatabricksJobsAdminTools requires validated admin settings before creating a workspace client."
                )
            self._workspace_client = workspace_client_cls(
                **build_workspace_client_kwargs(self.settings, azure_tenant_id=self.azure_tenant_id)
            )
        return self._workspace_client

    def create_job(self, job_settings: Dict[str, Any]) -> str:
        """Use this function to create a Databricks job from a JSON-like settings dictionary."""
        try:
            response = self.client.jobs.create(**self._normalize_job_settings(job_settings))
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error creating Databricks job: {str(e)}")
            return "Error creating Databricks job: An internal error occurred. Check server logs for details."

    def update_job(self, job_id: int, new_settings: Dict[str, Any], fields_to_remove: Optional[List[str]] = None) -> str:
        """Use this function to update a Databricks job using the Jobs update API."""
        try:
            self.client.jobs.update(
                job_id=job_id,
                new_settings=self._normalize_job_settings(new_settings),
                fields_to_remove=fields_to_remove,
            )
            return json.dumps({"job_id": job_id, "updated": True})
        except Exception as e:
            log_error(f"Error updating Databricks job: {str(e)}")
            return "Error updating Databricks job: An internal error occurred. Check server logs for details."

    def delete_job(self, job_id: int) -> str:
        """Use this function to permanently delete a Databricks job."""
        try:
            self.client.jobs.delete(job_id=job_id)
            return json.dumps({"job_id": job_id, "deleted": True})
        except Exception as e:
            log_error(f"Error deleting Databricks job: {str(e)}")
            return "Error deleting Databricks job: An internal error occurred. Check server logs for details."

    def submit_one_time_run(self, run_settings: Dict[str, Any]) -> str:
        """Use this function to submit a one-time Databricks run without creating a persistent job."""
        try:
            response = self.client.jobs.submit(**self._normalize_submit_settings(run_settings))
            return json.dumps(self._serialize_item(response), default=str)
        except Exception as e:
            log_error(f"Error submitting Databricks one-time run: {str(e)}")
            return "Error submitting Databricks one-time run: An internal error occurred. Check server logs for details."

    def _normalize_job_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(settings)
        needs_sdk_conversion = any(
            [
                isinstance(normalized.get("tasks"), list),
                isinstance(normalized.get("job_clusters"), list),
                isinstance(normalized.get("environments"), list),
                isinstance(normalized.get("queue"), dict),
                isinstance(normalized.get("schedule"), dict),
                isinstance(normalized.get("run_as"), dict),
                isinstance(normalized.get("continuous"), dict),
                isinstance(normalized.get("trigger"), dict),
                isinstance(normalized.get("git_source"), dict),
            ]
        )
        if not needs_sdk_conversion:
            return normalized

        _, jobs_service = _get_jobs_sdk()

        if isinstance(normalized.get("tasks"), list):
            normalized["tasks"] = [
                task if hasattr(task, "as_dict") else jobs_service.Task.from_dict(task) for task in normalized["tasks"]
            ]
        if isinstance(normalized.get("job_clusters"), list):
            normalized["job_clusters"] = [
                cluster if hasattr(cluster, "as_dict") else jobs_service.JobCluster.from_dict(cluster)
                for cluster in normalized["job_clusters"]
            ]
        if isinstance(normalized.get("environments"), list):
            normalized["environments"] = [
                env if hasattr(env, "as_dict") else jobs_service.JobEnvironment.from_dict(env)
                for env in normalized["environments"]
            ]
        if isinstance(normalized.get("queue"), dict):
            normalized["queue"] = jobs_service.QueueSettings.from_dict(normalized["queue"])
        if isinstance(normalized.get("schedule"), dict):
            normalized["schedule"] = jobs_service.CronSchedule.from_dict(normalized["schedule"])
        if isinstance(normalized.get("run_as"), dict):
            normalized["run_as"] = jobs_service.JobRunAs.from_dict(normalized["run_as"])
        if isinstance(normalized.get("continuous"), dict):
            normalized["continuous"] = jobs_service.Continuous.from_dict(normalized["continuous"])
        if isinstance(normalized.get("trigger"), dict):
            normalized["trigger"] = jobs_service.TriggerSettings.from_dict(normalized["trigger"])
        if isinstance(normalized.get("git_source"), dict):
            normalized["git_source"] = jobs_service.GitSource.from_dict(normalized["git_source"])

        return normalized

    def _normalize_submit_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(settings)
        needs_sdk_conversion = isinstance(normalized.get("tasks"), list) or isinstance(normalized.get("git_source"), dict)
        if not needs_sdk_conversion:
            return normalized

        _, jobs_service = _get_jobs_sdk()

        if isinstance(normalized.get("tasks"), list):
            normalized["tasks"] = [
                task if hasattr(task, "as_dict") else jobs_service.SubmitTask.from_dict(task)
                for task in normalized["tasks"]
            ]
        if isinstance(normalized.get("git_source"), dict):
            normalized["git_source"] = jobs_service.GitSource.from_dict(normalized["git_source"])

        return normalized

    def _serialize_item(self, item: Any) -> Dict[str, Any]:
        from agno.tools.databricks_tool_utils import serialize_sdk_item
        return serialize_sdk_item(item)
