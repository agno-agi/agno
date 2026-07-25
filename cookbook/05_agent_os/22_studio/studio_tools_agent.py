"""
Serve a Studio Agent that composes persisted components
=======================================================

AgentOS exposes code-defined Agents alongside components created by StudioTools.
The Studio Agent can discover registry primitives and compose Agents, Teams, and
Workflows while versioning keeps edits in drafts until publication.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_tools_agent.py
Try: run this file with --demo in another terminal
"""

import argparse
import os
from pathlib import Path
from uuid import uuid4

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.registry import Registry
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioTools

# ---------------------------------------------------------------------------
# Create Studio AgentOS
# ---------------------------------------------------------------------------

PORT = int(os.getenv("PORT", "7777"))
BASE_URL = os.getenv("AGENT_OS_BASE_URL", f"http://127.0.0.1:{PORT}")
STUDIO_AGENT_ID = "studio-agent"

DB_DIR = Path(__file__).parent / "tmp"
DB_DIR.mkdir(exist_ok=True)

db = SqliteDb(
    id="studio-tools-db",
    db_file=str(DB_DIR / "studio_tools.db"),
)

registry = Registry(
    name="Studio Registry",
    tools=[CalculatorTools()],
    models=[
        OpenAIResponses(id="gpt-5.5"),
        Claude(id="claude-sonnet-4-6"),
    ],
    dbs=[db],
)

greeter = Agent(
    id="greeter",
    name="Greeter",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Welcome the user in one sentence.",
    db=db,
)

reporter = Agent(
    id="reporter",
    name="Reporter",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="Summarize supplied facts in two sentences.",
    db=db,
)

studio_tools = StudioTools(
    registry=registry,
    db=db,
    agents_list=[greeter, reporter],
    default_model_id="gpt-5.5",
    versions=True,
)

studio_agent = Agent(
    id=STUDIO_AGENT_ID,
    name="Studio Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[studio_tools],
    instructions=[
        "Use StudioTools to compose persisted components from registry primitives.",
        "Discover exact model and tool names before creating a component.",
        "Report the component id, database version, and next versioning action.",
    ],
    db=db,
    markdown=True,
)

agent_os = AgentOS(
    id="studio-tools-os",
    name="Studio Tools AgentOS",
    description="AgentOS with code-defined and Studio-created components.",
    agents=[greeter, reporter, studio_agent],
    registry=registry,
    db=db,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Studio AgentOS
# ---------------------------------------------------------------------------


def run_demo() -> None:
    """Use the live Studio Agent to create one persisted Agent."""
    component_id = f"api-math-guide-{uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=180.0) as client:
        registry_response = client.get("/registry", params={"limit": 100})
        registry_response.raise_for_status()
        registry_names = {item["name"] for item in registry_response.json()["data"]}
        if "calculator" not in registry_names or "gpt-5.5" not in registry_names:
            raise RuntimeError("Registry discovery omitted the expected model or tool")

        response = client.post(
            f"/agents/{STUDIO_AGENT_ID}/runs",
            data={
                "message": (
                    "Call list_models and list_tools, then create an agent named "
                    f"'{component_id}' with model 'gpt-5.5', exact tool name "
                    "'calculator', and instructions 'Explain arithmetic clearly.' "
                    "Do not edit or run it."
                ),
                "session_id": f"studio-tools-{component_id}",
                "stream": "false",
            },
        )
        response.raise_for_status()
        run = response.json()
        if run["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {run['status']}")

        component_response = client.get(f"/components/{component_id}")
        component_response.raise_for_status()
        component = component_response.json()
        if component.get("current_version") != 1:
            raise RuntimeError(f"Expected published version 1, got {component}")

    print(f"Run: {run['run_id']} -> {run['status']}")
    print(f"Component: {component['component_id']} v{component['current_version']}")
    print(run.get("content"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against a server already listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, host="127.0.0.1", port=PORT)
