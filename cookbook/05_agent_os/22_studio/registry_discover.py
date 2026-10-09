"""
Control what AgentOS discovers into the Registry
================================================

By default AgentOS adds what it finds on the components it serves to the
registry: their tools, models, dbs, knowledge, and the agents, teams and
workflows themselves. GET /registry then lists them, and components built in
Studio can use them, including an internal agent's tools or the internal agent
itself as a team member.

Registry(discover=...) controls this. False keeps only what is declared on the
registry; a set of resource types discovers only those kinds.

Prerequisites: none; no model is called
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_discover.py
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


def registry_names(registry: Registry) -> dict:
    agent_os = AgentOS(agents=[internal_agent], registry=registry, telemetry=False)
    client = TestClient(agent_os.get_app())
    response = client.get("/registry", params={"limit": 100})
    response.raise_for_status()
    names: dict = {}
    for item in response.json()["data"]:
        names.setdefault(item["type"], set()).add(item["name"])
    return names


# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    default = registry_names(Registry(tools=[CalculatorTools()], models=[model]))
    declared_only = registry_names(
        Registry(tools=[CalculatorTools()], models=[model], discover=False)
    )
    models_only = registry_names(
        Registry(tools=[CalculatorTools()], discover={"model"})
    )

    print(
        f"discover=True:      tools={sorted(default.get('tool', []))} agents={sorted(default.get('agent', []))}"
    )
    print(
        f"discover=False:     tools={sorted(declared_only.get('tool', []))} agents={sorted(declared_only.get('agent', []))}"
    )
    print(
        f"discover={{'model'}}: tools={sorted(models_only.get('tool', []))} models={sorted(models_only.get('model', []))}"
    )

    assert {"run_sql", "send_email"} <= default["tool"]
    assert "Internal Agent" in default["agent"]
    assert declared_only["tool"] == {"calculator"}
    assert "agent" not in declared_only
    assert models_only["tool"] == {"calculator"}
    assert "gpt-5.6-luna" in models_only["model"]
