"""
Place persistent approval tools on a team leader or member
==========================================================

AgentOS propagates approval pauses differently depending on where the tool
lives. ``leader-approval-team`` owns its approval tool directly;
``member-approval-team`` delegates to a member that owns the tool. The client
runs both cases, resolves each persistent approval by ID, applies the approved
decision to the returned requirement, and continues the paused team.

Prerequisites: OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/05_human_in_the_loop/team_approval.py
Try: Run this file with --demo in another terminal
"""

import argparse
import json
from typing import Any

import httpx
from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.team import Team
from agno.tools import tool

# ---------------------------------------------------------------------------
# Create Approval Teams
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
LEADER_TEAM_ID = "leader-approval-team"
MEMBER_TEAM_ID = "member-approval-team"


@approval(type="required")
@tool()
def approve_release(service: str, version: str) -> str:
    """Approve a release from a tool owned by the team leader."""
    return f"Leader approved {service} version {version}"


@approval(type="required")
@tool()
def approve_database_change(change: str) -> str:
    """Approve a database change from a tool owned by a member agent."""
    return f"Database specialist approved: {change}"


db = SqliteDb(
    id="team-approval-db",
    db_file="tmp/agent_os_team_approval.db",
    approvals_table="approvals",
)

database_specialist = Agent(
    id="database-specialist",
    name="Database Specialist",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[approve_database_change],
    instructions=(
        "For every database change request, call approve_database_change "
        "immediately. The approval system handles the decision."
    ),
)

leader_approval_team = Team(
    id=LEADER_TEAM_ID,
    name="Leader Approval Team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[],
    tools=[approve_release],
    instructions=(
        "For every release request, call approve_release immediately. "
        "The approval system handles the decision."
    ),
    store_member_responses=True,
)

member_approval_team = Team(
    id=MEMBER_TEAM_ID,
    name="Member Approval Team",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    members=[database_specialist],
    instructions="Delegate every database change to the Database Specialist.",
    store_member_responses=True,
)

agent_os = AgentOS(
    id="team-approval-os",
    db=db,
    agents=[database_specialist],
    teams=[leader_approval_team, member_approval_team],
)
app = agent_os.get_app()


def find_approval_id(value: Any) -> str | None:
    """Find an approval ID in a serialized team pause."""
    if isinstance(value, dict):
        approval_id = value.get("approval_id")
        if isinstance(approval_id, str):
            return approval_id
        for child in value.values():
            found = find_approval_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_approval_id(child)
            if found:
                return found
    return None


def run_team_case(
    client: httpx.Client,
    team_id: str,
    session_id: str,
    message: str,
) -> None:
    """Resolve and continue one team approval regardless of tool ownership."""
    response = client.post(
        f"/teams/{team_id}/runs",
        data={
            "message": message,
            "session_id": session_id,
            "stream": "false",
        },
    )
    response.raise_for_status()
    paused = response.json()
    if paused["status"] != "PAUSED":
        raise RuntimeError(f"Expected PAUSED for {team_id}, got {paused['status']}")

    approval_id = find_approval_id(paused.get("requirements"))
    if approval_id is None:
        response = client.get(
            "/approvals",
            params={"status": "pending", "approval_type": "required"},
        )
        response.raise_for_status()
        approvals = response.json().get("data") or []
        if len(approvals) != 1:
            raise RuntimeError(f"Could not identify the pending approval for {team_id}")
        approval_id = approvals[0]["id"]

    response = client.get(f"/approvals/{approval_id}")
    response.raise_for_status()
    record = response.json()
    print(
        f"{team_id}: approval source={record['source_type']} tool={record['tool_name']}"
    )

    response = client.post(
        f"/approvals/{approval_id}/resolve",
        json={
            "status": "approved",
            "resolved_by": "cookbook-admin",
        },
    )
    response.raise_for_status()

    requirements = paused.get("requirements") or []
    for requirement in requirements:
        tool_execution = requirement.get("tool_execution") or {}
        if tool_execution.get("requires_confirmation"):
            requirement["confirmation"] = True
            tool_execution["confirmed"] = True

    response = client.post(
        f"/teams/{team_id}/runs/{paused['run_id']}/continue",
        data={
            "requirements": json.dumps(requirements),
            "session_id": paused["session_id"],
            "stream": "false",
        },
    )
    response.raise_for_status()
    continued = response.json()
    if continued["status"] != "COMPLETED":
        raise RuntimeError(
            f"Expected COMPLETED for {team_id}, got {continued['status']}"
        )
    print(f"{team_id}: final status={continued['status']}")


def run_demo() -> None:
    """Exercise leader-owned and member-owned persistent approvals."""
    with httpx.Client(base_url=BASE_URL, timeout=120.0) as client:
        run_team_case(
            client,
            team_id=LEADER_TEAM_ID,
            session_id="leader-approval-demo",
            message="Release billing version 3.1.0.",
        )
        run_team_case(
            client,
            team_id=MEMBER_TEAM_ID,
            session_id="member-approval-demo",
            message="Approve adding an index to the invoices table.",
        )


# ---------------------------------------------------------------------------
# Run Approval Teams
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run both HTTP clients against a server listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)
