"""
Return an externally executed tool result to AgentOS
====================================================

A member agent requests ``send_email``, but ``external_execution=True`` keeps
the side effect outside the AgentOS process. The client reads the requested
arguments, performs a deterministic stand-in for the external action, stores
the result on the returned requirement, and continues the paused team run.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/external_execution.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json
from typing import Any

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create External Execution Team
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
TEAM_ID = "communications-team"
SESSION_ID = "external-execution-demo"


@tool(external_execution=True)
def send_email(to: str, subject: str, body: str) -> str:
    """Describe an email operation that must run in the client process."""
    return ""


db = SqliteDb(
    id="external-execution-db",
    db_file="tmp/agent_os_hitl_external_execution.db",
)

email_agent = Agent(
    id="email-agent",
    name="Email Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[send_email],
    instructions=(
        "When asked to send an email, call send_email immediately. "
        "Do not simulate the result or ask follow-up questions."
    ),
)

communications_team = Team(
    id=TEAM_ID,
    name="Communications Team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[email_agent],
    instructions="Delegate every email request to the Email Agent.",
    store_member_responses=True,
)

agent_os = AgentOS(
    id="external-execution-os",
    db=db,
    agents=[email_agent],
    teams=[communications_team],
)
app = agent_os.get_app()


def execute_pending_tools(requirements: list[dict[str, Any]]) -> None:
    """Attach one external result to every pending tool requirement."""
    for requirement in requirements:
        tool_execution = requirement.get("tool_execution") or {}
        if not tool_execution.get("external_execution_required"):
            continue
        arguments = tool_execution.get("tool_args") or {}
        print(
            "External client sent email to "
            f"{arguments.get('to')} with subject {arguments.get('subject')}"
        )
        result = "External mail provider accepted message demo-message-001"
        requirement["external_execution_result"] = result
        tool_execution["result"] = result


def run_demo() -> None:
    """Pause for external execution, attach the result, and continue the run."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/teams/{TEAM_ID}/runs",
            data={
                "message": (
                    "Email ops@example.com with subject 'Maintenance' and body "
                    "'The maintenance window starts at 18:00 UTC.'"
                ),
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        response.raise_for_status()
        paused = response.json()
        if paused["status"] != "PAUSED":
            raise RuntimeError(f"Expected PAUSED, got {paused['status']}")

        requirements = paused.get("requirements") or []
        if not requirements:
            raise RuntimeError("The paused team run returned no requirements")
        execute_pending_tools(requirements)

        response = client.post(
            f"/teams/{TEAM_ID}/runs/{paused['run_id']}/continue",
            data={
                "requirements": json.dumps(requirements),
                "session_id": paused["session_id"],
                "stream": "false",
            },
        )
        response.raise_for_status()
        continued = response.json()
        if continued["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {continued['status']}")
        print(f"Final status: {continued['status']}")
        print(f"Result: {continued.get('content')}")


# ---------------------------------------------------------------------------
# Run External Execution Team
# ---------------------------------------------------------------------------

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
        agent_os.serve(app=app, port=7777)
