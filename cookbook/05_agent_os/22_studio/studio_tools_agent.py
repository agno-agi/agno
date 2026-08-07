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
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.registry import Registry
from agno.run import RunContext
from agno.tools.calculator import CalculatorTools
from agno.tools.studio import StudioAccess, StudioAction, StudioTools
from agno.tools.studio_schema import ModelRef

# ---------------------------------------------------------------------------
# Create Studio AgentOS
# ---------------------------------------------------------------------------

PORT = int(os.getenv("PORT", "7777"))
BASE_URL = os.getenv("AGENT_OS_BASE_URL", f"http://127.0.0.1:{PORT}")
OS_ID = "studio-tools-os"
STUDIO_AGENT_ID = "studio-agent"
STUDIO_ADMIN_USER_ID = "studio-admin"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY",
    "studio-tools-development-secret-at-least-256-bits-long",
)


def authorize_studio_admin(
    run_context: RunContext,
    _access: StudioAccess,
    _action: StudioAction,
) -> bool:
    """Limit the administrative Studio surface to the demo admin."""
    return run_context.user_id == STUDIO_ADMIN_USER_ID


def make_studio_admin_token() -> str:
    """Mint a short-lived, audience-bound token for the local HTTP demo."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": STUDIO_ADMIN_USER_ID,
            "aud": OS_ID,
            "scopes": ["agent_os:admin"],
            "iat": now,
            "exp": now + timedelta(minutes=15),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


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
    authorize=authorize_studio_admin,
    agents_list=[greeter, reporter],
    default_model=ModelRef(
        id="gpt-5.5",
        provider="OpenAI",
        name="OpenAIResponses",
    ),
)

studio_agent = Agent(
    id=STUDIO_AGENT_ID,
    name="Studio Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[studio_tools],
    instructions=[
        "Use StudioTools as an administrative control plane for persisted components.",
        "Discover and copy exact typed model and tool references before creating a component.",
        "Creates are drafts by default; publish only when the user explicitly asks.",
        "Use expected_version and expected_current_version as compare-and-set guards.",
        "Report result.status plus data.component_id, data.version, and data.stage.",
    ],
    db=db,
    markdown=True,
)

agent_os = AgentOS(
    id=OS_ID,
    name="Studio Tools AgentOS",
    description="AgentOS with code-defined and Studio-created components.",
    agents=[greeter, reporter, studio_agent],
    registry=registry,
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[JWT_SECRET],
        algorithm="HS256",
        verify_audience=True,
    ),
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Studio AgentOS
# ---------------------------------------------------------------------------


def confirm_expected_actions(
    tools: list[dict[str, object]],
    component_id: str,
    expected_actions: list[str],
) -> list[str]:
    """Confirm only the next exact Studio actions requested by the HTTP demo."""
    pending = [
        tool
        for tool in tools
        if tool.get("requires_confirmation") is True and tool.get("confirmed") is None
    ]
    if not pending or len(pending) > len(expected_actions):
        raise RuntimeError(f"Unexpected Studio confirmations: {pending}")

    confirmed: list[str] = []
    for tool, expected_action in zip(pending, expected_actions):
        tool_name = tool.get("tool_name")
        tool_args = tool.get("tool_args")
        if tool_name != expected_action or not isinstance(tool_args, dict):
            raise RuntimeError(f"Unexpected confirmation request: {tool}")

        if tool_name == "create_agent":
            request = tool_args.get("request")
            valid_args = (
                isinstance(request, dict)
                and request.get("component_id") == component_id
                and tool_args.get("save_as", "draft") == "draft"
            )
        else:
            valid_args = (
                tool_name == "publish_component"
                and tool_args.get("component_id") == component_id
                and tool_args.get("version") == 1
                and tool_args.get("expected_current_version") is None
            )
        if not valid_args:
            raise RuntimeError(f"Unexpected {tool_name} arguments: {tool_args}")

        print(f"Confirming {tool_name}: {tool_args}")
        tool["confirmed"] = True
        confirmed.append(tool_name)
    return confirmed


def run_demo() -> None:
    """Use a verified admin JWT to create one persisted Agent."""
    component_id = f"api-math-guide-{uuid4().hex[:8]}"
    with httpx.Client(
        base_url=BASE_URL,
        timeout=180.0,
        headers={"Authorization": f"Bearer {make_studio_admin_token()}"},
    ) as client:
        registry_response = client.get("/registry", params={"limit": 100})
        registry_response.raise_for_status()
        registry_names = {item["name"] for item in registry_response.json()["data"]}
        if "calculator" not in registry_names or "gpt-5.5" not in registry_names:
            raise RuntimeError("Registry discovery omitted the expected model or tool")

        response = client.post(
            f"/agents/{STUDIO_AGENT_ID}/runs",
            data={
                "message": (
                    "Call list_models and list_tools. Then call create_agent with an "
                    f"AgentCreate request whose component_id is '{component_id}', "
                    "name is 'API Math Guide', instructions are 'Explain arithmetic "
                    "clearly.', model is the exact gpt-5.5 ModelRef, and tools contains "
                    "the exact calculator toolkit ToolRef. Keep the default draft, "
                    f"then publish '{component_id}' version 1 with "
                    "expected_current_version=null. Do not edit or run it."
                ),
                "session_id": f"studio-tools-{component_id}",
                "stream": "false",
            },
        )
        response.raise_for_status()
        run = response.json()
        rounds = 0
        expected_actions = ["create_agent", "publish_component"]
        confirmed_actions: list[str] = []
        while run["status"] == "PAUSED":
            tools = run.get("tools") or []
            if len(confirmed_actions) >= len(expected_actions):
                raise RuntimeError(f"Unexpected extra Studio pause: {tools}")
            confirmed_actions.extend(
                confirm_expected_actions(
                    tools,
                    component_id,
                    expected_actions[len(confirmed_actions) :],
                )
            )
            response = client.post(
                f"/agents/{STUDIO_AGENT_ID}/runs/{run['run_id']}/continue",
                data={
                    "tools": json.dumps(tools),
                    "session_id": run["session_id"],
                    "stream": "false",
                },
            )
            response.raise_for_status()
            run = response.json()
            rounds += 1
            if rounds > 4:
                raise RuntimeError(
                    "Studio Agent did not finish after four lifecycle continuations"
                )
        if confirmed_actions != expected_actions:
            raise RuntimeError(
                f"Expected confirmations {expected_actions}, got {confirmed_actions}"
            )
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
