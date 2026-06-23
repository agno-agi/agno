import json

import pytest

from agno.tools.databricks_jobs import DatabricksJobsTools


class _SdkObject:
    def __init__(self, payload):
        self._payload = payload

    def as_dict(self):
        return self._payload


class _Waiter:
    def __init__(self, response):
        self.response = response


def test_list_jobs_serializes_results():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.jobs = type("JobsApi", (), {})()
    captured = {}

    def _list(name, expand_tasks, limit):
        captured["args"] = {"name": name, "expand_tasks": expand_tasks, "limit": limit}
        return [_SdkObject({"job_id": 1, "settings": {"name": "daily"}})]

    workspace_client.jobs.list = _list

    tools = DatabricksJobsTools(workspace_client=workspace_client)
    result = tools.list_jobs(name_contains="daily", limit=10)

    assert captured["args"] == {"name": "daily", "expand_tasks": False, "limit": 10}
    assert json.loads(result) == [{"job_id": 1, "settings": {"name": "daily"}}]


def test_get_job_and_get_run():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.jobs = type("JobsApi", (), {})()
    workspace_client.jobs.get = lambda job_id: _SdkObject({"job_id": job_id})
    workspace_client.jobs.get_run = lambda run_id: _SdkObject({"run_id": run_id})

    tools = DatabricksJobsTools(workspace_client=workspace_client)

    assert json.loads(tools.get_job(12)) == {"job_id": 12}
    assert json.loads(tools.get_job_run(99)) == {"run_id": 99}


def test_list_job_runs_forwards_filters():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.jobs = type("JobsApi", (), {})()
    captured = {}

    def _list_runs(job_id, active_only, completed_only, limit):
        captured["args"] = {
            "job_id": job_id,
            "active_only": active_only,
            "completed_only": completed_only,
            "limit": limit,
        }
        return [_SdkObject({"run_id": 55})]

    workspace_client.jobs.list_runs = _list_runs

    tools = DatabricksJobsTools(workspace_client=workspace_client)
    result = tools.list_job_runs(job_id=7, active_only=True, completed_only=False, limit=5)

    assert captured["args"] == {"job_id": 7, "active_only": True, "completed_only": False, "limit": 5}
    assert json.loads(result) == [{"run_id": 55}]


def test_run_job_now_forwards_parameters():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.jobs = type("JobsApi", (), {})()
    captured = {}

    def _run_now(job_id, notebook_params, job_parameters, python_params, only):
        captured["args"] = {
            "job_id": job_id,
            "notebook_params": notebook_params,
            "job_parameters": job_parameters,
            "python_params": python_params,
            "only": only,
        }
        return _Waiter(_SdkObject({"run_id": 321, "number_in_job": 4}))

    workspace_client.jobs.run_now = _run_now

    tools = DatabricksJobsTools(workspace_client=workspace_client, enable_admin_tools=True)
    result = tools.run_job_now(
        11,
        notebook_params={"date": "2026-04-08"},
        job_parameters={"env": "dev"},
        python_params=["--force"],
        only_tasks=["extract"],
    )

    assert captured["args"] == {
        "job_id": 11,
        "notebook_params": {"date": "2026-04-08"},
        "job_parameters": {"env": "dev"},
        "python_params": ["--force"],
        "only": ["extract"],
    }
    assert json.loads(result) == {"run_id": 321, "number_in_job": 4}


def test_cancel_job_run_and_confirmation_flags():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.jobs = type("JobsApi", (), {})()
    workspace_client.jobs.cancel_run = lambda run_id: _SdkObject({"run_id": run_id, "cancelled": True})

    tools = DatabricksJobsTools(workspace_client=workspace_client, enable_admin_tools=True)
    result = tools.cancel_job_run(42)

    assert "run_job_now" in tools.requires_confirmation_tools
    assert "cancel_job_run" in tools.requires_confirmation_tools
    assert json.loads(result) == {"run_id": 42, "cancelled": True}


def test_jobs_tools_hide_admin_operations_by_default():
    tools = DatabricksJobsTools(workspace_client=object())

    assert "run_job_now" not in tools.functions
    assert "cancel_job_run" not in tools.functions
    assert tools.requires_confirmation_tools == []


def test_jobs_tools_reject_admin_operations_without_enable_flag():
    workspace_client = type("WorkspaceClient", (), {})()
    workspace_client.jobs = type("JobsApi", (), {})()
    tools = DatabricksJobsTools(workspace_client=workspace_client)

    run_result = tools.run_job_now(11)
    cancel_result = tools.cancel_job_run(42)

    assert "enable_admin_tools=True" in run_result
    assert "enable_admin_tools=True" in cancel_result


def test_jobs_tools_require_explicit_admin_credentials_without_injected_client():
    with pytest.raises(ValueError, match="explicit admin credentials"):
        DatabricksJobsTools(enable_admin_tools=True)
