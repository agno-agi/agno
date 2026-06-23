import os

import pytest

from agno.tools.databricks_vector_search import DatabricksVectorSearchTools


@pytest.fixture
def tools():
    return DatabricksVectorSearchTools(
        host=os.environ.get("DATABRICKS_HOST"),
        token=os.environ.get("DATABRICKS_TOKEN"),
        default_endpoint_name=os.environ.get("DATABRICKS_VECTOR_SEARCH_ENDPOINT"),
        default_index_name=os.environ.get("DATABRICKS_VECTOR_SEARCH_INDEX"),
    )


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST") or not os.environ.get("DATABRICKS_TOKEN"),
    reason="Databricks credentials not set",
)
def test_list_endpoints(tools):
    result = tools.list_endpoints(limit=10)
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"


@pytest.mark.skipif(
    not os.environ.get("DATABRICKS_HOST")
    or not os.environ.get("DATABRICKS_TOKEN")
    or not os.environ.get("DATABRICKS_VECTOR_SEARCH_ENDPOINT")
    or not os.environ.get("DATABRICKS_VECTOR_SEARCH_INDEX"),
    reason="Databricks vector search credentials not set",
)
def test_describe_index(tools):
    result = tools.describe_index()
    assert isinstance(result, str)
    assert not result.startswith("Error "), f"Tool returned error: {result}"
