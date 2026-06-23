"""
Databricks Jobs Admin Tools
===========================

Demonstrates the Databricks jobs admin toolkit surface.
"""

import json
import os

from agno.tools.databricks_jobs_admin import DatabricksJobsAdminTools


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


tools = DatabricksJobsAdminTools(
    host=_require_env("DATABRICKS_HOST"),
    admin_token=_require_env("DATABRICKS_ADMIN_TOKEN"),
    enable_admin_tools=True,
)


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "functions": list(tools.functions.keys()),
                "requires_confirmation": tools.requires_confirmation_tools,
            },
            indent=2,
        )
    )
