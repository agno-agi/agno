"""
Resolve a persistent AgentOS approval record
============================================

``@approval(type="required")`` creates a database-backed approval record in
addition to pausing the run. The client finds that record with
``GET /approvals``, resolves it with ``POST /approvals/{id}/resolve``, and then
continues the run without resending a tool decision.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/with_approval_record.py
Try: Run this file with --demo in another terminal
"""

import argparse

import httpx
from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Approval-Backed AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
AGENT_ID = "approval-record-agent"
SESSION_ID = "approval-record-demo"


@approval(type="required")
@tool()
def deploy_release(service: str, version: str) -> str:
    """Deploy one service version after an administrator approves the record."""
    return f"Deployed {service} at version {version}"


db = SqliteDb(
    id="approval-record-db",
    db_file="tmp/agent_os_required_approval.db",
    approvals_table="approvals",
)

approval_agent = Agent(
    id=AGENT_ID,
    name="Approval Record Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[deploy_release],
    instructions=(
        "When asked to deploy a release, call deploy_release immediately. "
        "The approval system handles the administrative decision."
    ),
)

agent_os = AgentOS(
    id="approval-record-os",
    db=db,
    agents=[approval_agent],
)
app = agent_os.get_app()


def get_approval(client: httpx.Client, run_id: str) -> dict:
    """Return the required approval record created for one paused run."""
    response = client.get(
        "/approvals",
        params={
            "run_id": run_id,
            "status": "pending",
            "approval_type": "required",
        },
    )
    response.raise_for_status()
    approvals = response.json().get("data") or []
    if len(approvals) != 1:
        raise RuntimeError(f"Expected one pending approval, found {len(approvals)}")
    return approvals[0]


def run_demo() -> None:
    """Create, inspect, resolve, and continue one persistent approval."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        response = client.post(
            f"/agents/{AGENT_ID}/runs",
            data={
                "message": "Deploy billing version 2.4.1.",
                "session_id": SESSION_ID,
                "stream": "false",
            },
        )
        response.raise_for_status()
        paused = response.json()
        if paused["status"] != "PAUSED":
            raise RuntimeError(f"Expected PAUSED, got {paused['status']}")

        approval_record = get_approval(client, paused["run_id"])
        print(f"Approval record: {approval_record['id']} ({approval_record['status']})")

        response = client.post(
            f"/approvals/{approval_record['id']}/resolve",
            json={
                "status": "approved",
                "resolved_by": "cookbook-admin",
            },
        )
        response.raise_for_status()
        resolved = response.json()
        if resolved["status"] != "approved":
            raise RuntimeError(f"Expected approved, got {resolved['status']}")

        response = client.post(
            f"/agents/{AGENT_ID}/runs/{paused['run_id']}/continue",
            data={
                "session_id": paused["session_id"],
                "stream": "false",
            },
        )
        response.raise_for_status()
        continued = response.json()
        if continued["status"] != "COMPLETED":
            raise RuntimeError(f"Expected COMPLETED, got {continued['status']}")
        print(f"Resolved by: {resolved['resolved_by']}")
        print(f"Final status: {continued['status']}")
        print(f"Result: {continued.get('content')}")


# ---------------------------------------------------------------------------
# Run Approval-Backed AgentOS
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
