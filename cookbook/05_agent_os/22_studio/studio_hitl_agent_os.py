"""
Resolve Studio composition pauses through AgentOS
=================================================

This AgentOS lesson exposes the same three Studio pauses as the console lesson,
but serializes them as Agent run tools. The demo updates those tool payloads and
posts them to the nested continuation endpoint.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_hitl_agent_os.py
Try: run this file with --demo in another terminal
"""

import argparse
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
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
from agno.tools.user_control_flow import UserControlFlowTools
from agno.tools.user_feedback import UserFeedbackTools

# ---------------------------------------------------------------------------
# Create AgentOS HITL Studio Agent
# ---------------------------------------------------------------------------

PORT = int(os.getenv("PORT", "7777"))
BASE_URL = os.getenv("AGENT_OS_BASE_URL", f"http://127.0.0.1:{PORT}")
OS_ID = "studio-hitl-os"
AGENT_ID = "studio-hitl-agent"
AUTO_INSTRUCTIONS = "Explain reliable research methods in concise steps."
STUDIO_ADMIN_USER_ID = "studio-admin"
JWT_SECRET = os.getenv(
    "JWT_VERIFICATION_KEY",
    "studio-hitl-development-secret-at-least-256-bits-long",
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
    id="studio-hitl-agentos-db",
    db_file=str(DB_DIR / "studio_hitl_agentos.db"),
)

registry = Registry(
    name="AgentOS HITL Studio Registry",
    tools=[CalculatorTools()],
    models=[
        OpenAIResponses(id="gpt-5.5"),
        Claude(id="claude-sonnet-4-6"),
    ],
    dbs=[db],
)

studio_agent = Agent(
    id=AGENT_ID,
    name="AgentOS HITL Studio Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    tools=[
        StudioTools(
            registry=registry,
            db=db,
            authorize=authorize_studio_admin,
            default_model=ModelRef(
                id="gpt-5.5",
                provider="OpenAI",
                name="OpenAIResponses",
            ),
        ),
        UserFeedbackTools(),
        UserControlFlowTools(),
    ],
    instructions=[
        "Help the user compose one Agent from registry primitives.",
        "Call list_tools and list_models first; Studio already has one fixed catalog database.",
        "If tools are missing, call ask_user with one multi-select question whose "
        "options are exact names returned by list_tools.",
        "If instructions are missing, call get_user_input with one string field.",
        "Do not combine the missing tool and instruction questions in chat.",
        "Translate each selected tool into the exact ToolRef returned by list_tools.",
        "Call create_agent with one AgentCreate request only after both answers are available.",
        "Keep the new component as a draft; publication is a separate admin decision.",
    ],
    db=db,
    markdown=True,
)

agent_os = AgentOS(
    id=OS_ID,
    name="Studio HITL AgentOS",
    description="Studio composition with API-visible human-in-the-loop pauses.",
    agents=[studio_agent],
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
# Run AgentOS HITL Studio Agent
# ---------------------------------------------------------------------------


def resolve_paused_tools(
    tools: list[dict[str, Any]],
    component_id: str,
) -> list[str]:
    """Resolve every active feedback, input, or confirmation tool payload."""
    observed: list[str] = []
    for tool in tools:
        feedback_schema = tool.get("user_feedback_schema") or []
        if feedback_schema and tool.get("answered") is not True:
            for question in feedback_schema:
                options = question.get("options") or []
                labels = [option["label"] for option in options]
                selected = ["calculator"] if "calculator" in labels else labels[:1]
                question["selected_options"] = selected
                for option in options:
                    option["selected"] = option["label"] in selected
            tool["answered"] = True
            observed.append("user_feedback")
            continue

        input_schema = tool.get("user_input_schema") or []
        if input_schema and tool.get("answered") is not True:
            for field in input_schema:
                if field.get("value") is None:
                    field["value"] = AUTO_INSTRUCTIONS
            tool["answered"] = True
            observed.append("user_input")
            continue

        if tool.get("requires_confirmation") and tool.get("confirmed") is None:
            tool_args = tool.get("tool_args")
            request = tool_args.get("request") if isinstance(tool_args, dict) else None
            requested_id = (
                request.get("component_id") or request.get("name")
                if isinstance(request, dict)
                else None
            )
            if (
                tool.get("tool_name") != "create_agent"
                or requested_id != component_id
                or not isinstance(tool_args, dict)
                or tool_args.get("save_as", "draft") != "draft"
            ):
                raise RuntimeError(f"Unexpected Studio confirmation: {tool}")
            tool["confirmed"] = True
            observed.append("confirmation")

    if not observed:
        raise RuntimeError("Paused response did not contain a resolvable tool")
    return observed


def run_demo() -> None:
    """Resolve all three pause types as a verified Studio administrator."""
    component_id = f"os-research-buddy-{uuid4().hex[:8]}"
    session_id = f"studio-hitl-{component_id}"
    with httpx.Client(
        base_url=BASE_URL,
        timeout=180.0,
        headers={"Authorization": f"Bearer {make_studio_admin_token()}"},
    ) as client:
        response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": f"Create an agent called '{component_id}'.",
                "session_id": session_id,
                "stream": "false",
            },
        )
        response.raise_for_status()
        run = response.json()
        observed: list[str] = []
        rounds = 0

        while run["status"] == "PAUSED":
            tools = run.get("tools") or []
            observed.extend(resolve_paused_tools(tools, component_id))
            response = client.post(
                f"/agents/{AGENT_ID}/runs/{run['run_id']}/continue",
                data={
                    "tools": json.dumps(tools),
                    "session_id": run["session_id"],
                    "stream": "false",
                },
            )
            response.raise_for_status()
            run = response.json()
            rounds += 1
            if rounds > 6:
                raise RuntimeError(
                    "Studio Agent did not finish after six continuation rounds"
                )

        if run["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {run['status']}")
        expected = ["user_feedback", "user_input", "confirmation"]
        if observed != expected:
            raise RuntimeError(
                f"Expected pause sequence {expected}, observed {observed}"
            )

        component_response = client.get(f"/components/{component_id}")
        component_response.raise_for_status()
        component = component_response.json()
        config_response = client.get(f"/components/{component_id}/configs/1")
        config_response.raise_for_status()
        config = config_response.json()
        if component.get("current_version") is not None:
            raise RuntimeError(
                f"Expected a non-current draft component, got {component}"
            )
        if config.get("stage") != "draft":
            raise RuntimeError(f"Expected draft version 1, got {config}")

    print(f"Pause sequence: {observed}")
    print(f"Final run: {run['run_id']} -> {run['status']}")
    print(f"Created draft: {component['component_id']} v{config['version']}")
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
