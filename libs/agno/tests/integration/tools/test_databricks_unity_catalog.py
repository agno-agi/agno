import os

import pytest

from agno.tools.databricks_unity_catalog import DatabricksUnityCatalogTools


@pytest.fixture
def tools():
    return DatabricksUnityCatalogTools(
        host=os.environ.get("DATABRICKS_HOST"),
        token=os.environ.get("DATABRICKS_TOKEN"),
        default_catalog=os.environ.get("DATABRICKS_CATALOG"),
        default_schema=os.environ.get("DATABRICKS_SCHEMA"),
    )


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST") or not os.environ.get("DATABRICKS_TOKEN"),
    reason="Databricks credentials not set",
)
def test_list_catalogs(tools):
    result = tools.list_catalogs(limit=10)
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_CATALOG"),
    reason="Databricks catalog credentials not set",
)
def test_list_schemas(tools):
    result = tools.list_schemas(limit=10)
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"
