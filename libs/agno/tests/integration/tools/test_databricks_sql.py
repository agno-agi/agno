import os

import pytest

from agno.tools.databricks_sql import DatabricksSQLTools


@pytest.fixture
def tools():
    return DatabricksSQLTools(
        server_hostname=os.environ.get("DATABRICKS_SERVER_HOSTNAME") or os.environ.get("DATABRICKS_HOST"),
        http_path=os.environ.get("DATABRICKS_HTTP_PATH"),
        access_token=os.environ.get("DATABRICKS_TOKEN"),
        catalog=os.environ.get("DATABRICKS_CATALOG"),
        schema=os.environ.get("DATABRICKS_SCHEMA"),
    )


@pytest.mark.skipif(
    not (os.environ.get("DATABRICKS_SERVER_HOSTNAME") or os.environ.get("DATABRICKS_HOST"))
    or not os.environ.get("DATABRICKS_HTTP_PATH")
    or not os.environ.get("DATABRICKS_TOKEN"),
    reason="Databricks SQL credentials not set",
)
def test_list_catalogs(tools):
    result = tools.list_catalogs(limit=10)
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"


@pytest.mark.skipif(
    not (os.environ.get("DATABRICKS_SERVER_HOSTNAME") or os.environ.get("DATABRICKS_HOST"))
    or not os.environ.get("DATABRICKS_HTTP_PATH")
    or not os.environ.get("DATABRICKS_TOKEN"),
    reason="Databricks SQL credentials not set",
)
def test_run_sql_query(tools):
    result = tools.run_sql_query("SELECT 1 AS ok", limit=5)
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"
