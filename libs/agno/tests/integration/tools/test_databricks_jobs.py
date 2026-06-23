import os

import pytest

from agno.tools.databricks_jobs import DatabricksJobsTools


@pytest.fixture
def tools():
    return DatabricksJobsTools(
        host=os.environ.get("DATABRICKS_HOST"),
        token=os.environ.get("DATABRICKS_TOKEN"),
    )


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST") or not os.environ.get("DATABRICKS_TOKEN"),
    reason="Databricks credentials not set",
)
def test_list_jobs(tools):
    result = tools.list_jobs(limit=5)
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_JOB_ID"),
    reason="Databricks job credentials not set",
)
def test_get_job(tools):
    result = tools.get_job(int(os.environ["DATABRICKS_JOB_ID"]))
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"
