"""
Write an audit approval after an ephemeral HITL decision
========================================================

``@approval(type="audit")`` does not replace a HITL flag. It must be layered
on a tool that already uses ``requires_confirmation``,
``requires_user_input``, or ``external_execution``. This example confirms an
ephemeral pause through ``continue`` and then verifies that AgentOS wrote the
resolved audit row to ``GET /approvals``.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/audit_record.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json

import httpx
from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Audited HITL AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "audit-record-agent"
SESSION_ID = "audit-record-demo"


@approval(type="audit")
@tool(requires_confirmation=True)
def rotate_api_key(service: str) -> str:
    """Rotate one service key after an operator confirms the action."""
    return f"Rotated the API key for {service}"


db = SqliteDb(
    id="audit-record-db",
    db_file="tmp/agent_os_audit_approval.db",
    approvals_table="approvals",
)

audit_agent = Agent(
    id=AGENT_ID,
    name="Audit Record Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[rotate_api_key],
    instructions=(
        "When asked to rotate a key, call rotate_api_key immediately. "
        "The tool itself handles operator confirmation."
    ),
)

agent_os = AgentOS(
    id="audit-record-os",
    db=db,
    agents=[audit_agent],
)
app = agent_os.get_app()


def run_demo() -> None:
    """Confirm the pause and read back the audit record written on resolution."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Rotate the API key for the search service.",
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        response.raise_for_status()
        paused = response.json()
        if paused["status"] != "PAUSED":
            raise RuntimeError(f"Expected PAUSED, got {paused['status']}")

        pending_tools = paused.get("tools") or []
        for pending_tool in pending_tools:
            if pending_tool.get("requires_confirmation"):
                pending_tool["confirmed"] = True
        if not pending_tools:
            raise RuntimeError("The paused run returned no pending tool")

        response = client.post(
            f"/agents/{AGENT_ID}/runs/{paused['run_id']}/continue",
            data={
                "tools": json.dumps(pending_tools),
                "session_id": paused["session_id"],
                "stream": "false",
            },
        )
        response.raise_for_status()
        continued = response.json()
        if continued["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {continued['status']}")

        response = client.get(
            "/approvals",
            params={
                "run_id": paused["run_id"],
                "approval_type": "audit",
            },
        )
        response.raise_for_status()
        records = response.json().get("data") or []
        if len(records) != 1:
            raise RuntimeError(f"Expected one audit record, found {len(records)}")
        record = records[0]
        if record["status"] != "approved":
            raise RuntimeError(f"Expected approved audit row, got {record['status']}")

        print(f"Final status: {continued['status']}")
        print(
            "Audit record: "
            f"{record['id']} ({record['approval_type']}, {record['status']})"
        )


# ---------------------------------------------------------------------------
# Run Audited HITL AgentOS
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
