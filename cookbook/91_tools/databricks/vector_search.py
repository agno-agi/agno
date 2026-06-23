"""
Databricks Vector Search Tools
==============================

Demonstrates Databricks vector search inspection tools.
"""

import os

from agno.tools.databricks_vector_search import DatabricksVectorSearchTools


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


tools = DatabricksVectorSearchTools(
    host=_require_env("DATABRICKS_HOST"),
    token=_require_env("DATABRICKS_TOKEN"),
    default_endpoint_name=os.getenv("DATABRICKS_VECTOR_SEARCH_ENDPOINT"),
    default_index_name=os.getenv("DATABRICKS_VECTOR_SEARCH_INDEX"),
)


if __name__ == "__main__":
    print(tools.list_endpoints(limit=10))
    if os.getenv("DATABRICKS_VECTOR_SEARCH_INDEX"):
        print(tools.describe_index())
