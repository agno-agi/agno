"""
Databricks SQL Tools
====================

Demonstrates read-only Databricks SQL tools.
"""

import os

from agno.tools.databricks_sql import DatabricksSQLTools


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


tools = DatabricksSQLTools(
    server_hostname=_require_env("DATABRICKS_SERVER_HOSTNAME"),
    http_path=_require_env("DATABRICKS_HTTP_PATH"),
    access_token=_require_env("DATABRICKS_TOKEN"),
    catalog=os.getenv("DATABRICKS_CATALOG"),
    schema=os.getenv("DATABRICKS_SCHEMA"),
)


if __name__ == "__main__":
    print(tools.list_tables(limit=10))
