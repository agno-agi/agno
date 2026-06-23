"""
Databricks Unity Catalog Tools
==============================

Demonstrates Databricks Unity Catalog inspection tools.
"""

import os

from agno.tools.databricks_unity_catalog import DatabricksUnityCatalogTools


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


tools = DatabricksUnityCatalogTools(
    host=_require_env("DATABRICKS_HOST"),
    token=_require_env("DATABRICKS_TOKEN"),
    default_catalog=os.getenv("DATABRICKS_CATALOG"),
)


if __name__ == "__main__":
    print(tools.list_catalogs(limit=10))
