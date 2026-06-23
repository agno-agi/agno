"""
Databricks Jobs Tools
=====================

Demonstrates Databricks jobs inspection tools.
"""

import os

from agno.tools.databricks_jobs import DatabricksJobsTools


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


tools = DatabricksJobsTools(
    host=_require_env("DATABRICKS_HOST"),
    token=_require_env("DATABRICKS_TOKEN"),
)


if __name__ == "__main__":
    print(tools.list_jobs(limit=5))
