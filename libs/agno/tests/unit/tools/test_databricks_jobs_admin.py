import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from agno.tools.databricks_jobs_admin import DatabricksJobsAdminTools


class _SdkObject:
    def __init__(self, payload):
        self._payload = payload

    def as_dict(self):
        return self._payload


def test_create_job_uses_job_settings_from_dict():
    jobs_api = Mock()
    jobs_api.create.return_value = _SdkObject({"job_id": 123})
    workspace_client = SimpleNamespace(jobs=jobs_api)

    converted_task = Mock()
    converted_task.as_dict.return_value = {"task_key": "demo"}
    task_cls = Mock()
    task_cls.from_dict.return_value = converted_task
    jobs_service = SimpleNamespace(
        Task=task_cls,
        JobCluster=Mock(),
        JobEnvironment=Mock(),
        QueueSettings=Mock(),
        CronSchedule=Mock(),
        JobRunAs=Mock(),
        Continuous=Mock(),
        TriggerSettings=Mock(),
        GitSource=Mock(),
    )

    with patch("agno.tools.databricks_jobs_admin._get_jobs_sdk", return_value=(object, jobs_service)):
        tools = DatabricksJobsAdminTools(workspace_client=workspace_client, enable_admin_tools=True)
        result = tools.create_job({"name": "demo-job", "tasks": [{"task_key": "demo"}]})

    task_cls.from_dict.assert_called_once_with({"task_key": "demo"})
    jobs_api.create.assert_called_once_with(name="demo-job", tasks=[converted_task])
    assert json.loads(result) == {"job_id": 123}


def test_update_and_delete_job():
    jobs_api = Mock()
    workspace_client = SimpleNamespace(jobs=jobs_api)
    tools = DatabricksJobsAdminTools(workspace_client=workspace_client, enable_admin_tools=True)

    updated = tools.update_job(123, {"name": "demo-job-v2"}, fields_to_remove=["schedule"])
    deleted = tools.delete_job(123)

    jobs_api.update.assert_called_once_with(job_id=123, new_settings={"name": "demo-job-v2"}, fields_to_remove=["schedule"])
    jobs_api.delete.assert_called_once_with(job_id=123)
    assert json.loads(updated) == {"job_id": 123, "updated": True}
    assert json.loads(deleted) == {"job_id": 123, "deleted": True}


def test_submit_one_time_run():
    jobs_api = Mock()
    jobs_api.submit.return_value = _SdkObject({"run_id": 456})
    workspace_client = SimpleNamespace(jobs=jobs_api)
    submit_task = Mock()
    submit_task.as_dict.return_value = {"task_key": "adhoc"}
    jobs_service = SimpleNamespace(
        Task=Mock(),
        SubmitTask=Mock(),
        JobCluster=Mock(),
        JobEnvironment=Mock(),
        QueueSettings=Mock(),
        CronSchedule=Mock(),
        JobRunAs=Mock(),
        Continuous=Mock(),
        TriggerSettings=Mock(),
        GitSource=Mock(),
    )
    jobs_service.SubmitTask.from_dict.return_value = submit_task

    with patch("agno.tools.databricks_jobs_admin._get_jobs_sdk", return_value=(object, jobs_service)):
        tools = DatabricksJobsAdminTools(workspace_client=workspace_client, enable_admin_tools=True)
        result = tools.submit_one_time_run({"run_name": "adhoc", "tasks": [{"task_key": "adhoc"}]})

    jobs_service.SubmitTask.from_dict.assert_called_once_with({"task_key": "adhoc"})
    jobs_api.submit.assert_called_once_with(run_name="adhoc", tasks=[submit_task])
    assert json.loads(result) == {"run_id": 456}


def test_jobs_admin_confirmation_flags():
    tools = DatabricksJobsAdminTools(workspace_client=SimpleNamespace(jobs=Mock()), enable_admin_tools=True)

    assert "create_job" in tools.requires_confirmation_tools
    assert "update_job" in tools.requires_confirmation_tools
    assert "delete_job" in tools.requires_confirmation_tools
    assert "submit_one_time_run" in tools.requires_confirmation_tools


def test_jobs_admin_requires_explicit_enable_flag():
    with pytest.raises(ValueError, match="enable_admin_tools=True"):
        DatabricksJobsAdminTools(workspace_client=SimpleNamespace(jobs=Mock()))


def test_jobs_admin_requires_explicit_admin_credentials_without_workspace_client():
    with pytest.raises(ValueError, match="explicit admin credentials"):
        DatabricksJobsAdminTools(host="https://example.cloud.databricks.com", enable_admin_tools=True)


def test_jobs_admin_uses_dedicated_admin_token(monkeypatch):
    monkeypatch.setenv("DATABRICKS_TOKEN", "standard-token")
    monkeypatch.setenv("DATABRICKS_ADMIN_TOKEN", "admin-token")

    workspace_client_cls = Mock()
    workspace_client = SimpleNamespace(jobs=Mock())
    workspace_client_cls.return_value = workspace_client

    with patch("agno.tools.databricks_jobs_admin._get_jobs_sdk", return_value=(workspace_client_cls, object)):
        tools = DatabricksJobsAdminTools(
            host="https://env.cloud.databricks.com",
            enable_admin_tools=True,
        )
        assert tools.client == workspace_client

    workspace_client_cls.assert_called_once_with(
        host="https://env.cloud.databricks.com",
        token="admin-token",
    )
