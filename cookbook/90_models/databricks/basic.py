"""
Databricks Basic
================

Cookbook example for `databricks/basic.py`.
"""

import os

from agno.agent import Agent
from agno.models.databricks import Databricks


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


agent = Agent(
    model=Databricks(
        host=_require_env("DATABRICKS_HOST"),
        token=_require_env("DATABRICKS_TOKEN"),
        endpoint=_require_env("DATABRICKS_CHAT_ENDPOINT"),
    ),
    markdown=True,
)


if __name__ == "__main__":
    prompt = "Share a 2 sentence horror story."

    agent.print_response(prompt)
    agent.print_response(prompt, stream=True)
