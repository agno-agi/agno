"""Inspect the shared shipping project with Hermes's native file tools."""

from os import getenv
from pathlib import Path

from agno.agents.hermes import HermesAgent

workspace = Path(__file__).resolve().parents[1] / "sample_project"
agent = HermesAgent(
    name="Hermes Shipping Reviewer",
    model=getenv("HERMES_MODEL"),
    cwd=str(workspace),
    enabled_toolsets=["file"],
    instructions="Read the requested files and explain them. Do not modify files.",
    max_iterations=20,
)

if __name__ == "__main__":
    agent.print_response(
        "Read shipping.py and orders.json. Explain the shipping fee for each order.",
        stream=True,
    )
