"""
Expose only declared tools in the Registry
==========================================

By default AgentOS adds the tools of every agent and team it serves to the
registry, so GET /registry lists them and components built from the registry
can call them. When an internal agent carries tools that should never reach
user-built agents (SQL against the main database, outbound email, component
management), set auto_populate_registry_tools=False: the registry then lists
only the tools declared on it.

Prerequisites: none; no model is called
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_declared_tools_only.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from fastapi.testclient import TestClient


def run_sql(query: str) -> str:
    """Run a SQL query against the main database."""
    return "internal only"


def send_email(to: str, body: str) -> str:
    """Send an email on behalf of the company."""
    return "internal only"


# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------

model = OpenAIResponses(id="gpt-5.6-luna")

internal_agent = Agent(
    id="internal-agent",
    name="Internal Agent",
    model=model,
    tools=[run_sql, send_email],
)


def registry_tool_names(auto_populate_registry_tools: bool) -> set:
    agent_os = AgentOS(
        agents=[internal_agent],
        registry=Registry(tools=[CalculatorTools()], models=[model]),
        auto_populate_registry_tools=auto_populate_registry_tools,
        telemetry=False,
    )
    client = TestClient(agent_os.get_app())
    response = client.get("/registry", params={"resource_type": "tool"})
    response.raise_for_status()
    return {item["name"] for item in response.json()["data"]}


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    default_tools = registry_tool_names(auto_populate_registry_tools=True)
    declared_tools = registry_tool_names(auto_populate_registry_tools=False)

    print(f"Default registry tools: {sorted(default_tools)}")
    print(f"Declared-only registry tools: {sorted(declared_tools)}")

    assert {"run_sql", "send_email"} <= default_tools
    assert declared_tools == {"calculator"}
