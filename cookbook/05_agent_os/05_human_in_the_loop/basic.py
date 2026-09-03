"""
Confirm an ephemeral AgentOS tool call
======================================

Pause an agent run with ``@tool(requires_confirmation=True)``, inspect the
pending tool returned by AgentOS, confirm it, and send the updated tool to the
nested ``continue`` route. This pause exists only in the persisted run; it does
not create an approval record.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/basic.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Confirmation AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "confirmation-agent"
SESSION_ID = "confirmation-demo"


@tool(requires_confirmation=True)
def restart_service(service: str) -> str:
    """Restart one service after the caller confirms the action."""
    return f"Restarted {service}"


db = SqliteDb(
    id="confirmation-db",
    db_file="tmp/agent_os_hitl_basic.db",
)

confirmation_agent = Agent(
    id=AGENT_ID,
    name="Confirmation Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[restart_service],
    instructions=(
        "When asked to restart a service, call restart_service immediately. "
        "Do not ask for confirmation in chat because the tool enforces it."
    ),
)

agent_os = AgentOS(
    id="confirmation-os",
    db=db,
    agents=[confirmation_agent],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Pause, confirm the returned tool execution, and continue the same run."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Restart the billing service.",
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        response.raise_for_status()
        paused = response.json()
        if paused["status"] != "PAUSED":
            raise RuntimeError(f"Expected PAUSED, got {paused['status']}")

        pending_tools = paused.get("tools") or []
        if not pending_tools:
            raise RuntimeError("The paused run returned no pending tool")
        for pending_tool in pending_tools:
            if pending_tool.get("requires_confirmation"):
                pending_tool["confirmed"] = True

        continued_response = client.post(
            f"/agents/{AGENT_ID}/runs/{paused['run_id']}/continue",
            data={
                "tools": json.dumps(pending_tools),
                "session_id": paused["session_id"],
                "stream": "false",
            },
        )
        continued_response.raise_for_status()
        continued = continued_response.json()
        if continued["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {continued['status']}")

        print(f"Initial status: {paused['status']}")
        print("Confirmed tool: restart_service")
        print(f"Final status: {continued['status']}")
        print(f"Result: {continued.get('content')}")


# ---------------------------------------------------------------------------
# Run Confirmation AgentOS
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
