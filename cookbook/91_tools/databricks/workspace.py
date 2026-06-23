"""
Databricks Workspace Tools
==========================

Demonstrates Databricks workspace inspection tools.
"""

import os

from agno.tools.databricks_workspace import DatabricksWorkspaceTools


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


tools = DatabricksWorkspaceTools(
    host=_require_env("DATABRICKS_HOST"),
    token=_require_env("DATABRICKS_TOKEN"),
)


if __name__ == "__main__":
    print(tools.list_workspace_objects(path="/", limit=10))
