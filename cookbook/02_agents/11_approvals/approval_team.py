"""
Approval Team
=============================

Team-level approval: member agent tool with @approval.
"""

import os
import time

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools import tool

DB_FILE = "tmp/approvals_team_test.db"


@approval
@tool(requires_confirmation=True)
def deploy_to_production(app_name: str, version: str) -> str:
    """Deploy an application to production.

    Args:
        app_name (str): Name of the application.
        version (str): Version to deploy.
    """
    return f"Successfully deployed {app_name} v{version} to production"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    db_file=DB_FILE, session_table="team_sessions", approvals_table="approvals"
)

deploy_agent = Agent(
    name="Deploy Agent",
    role="Handles deployments to production",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[deploy_to_production],
)

team = Team(
    name="DevOps Team",
    members=[deploy_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Clean up from previous runs
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    os.makedirs("tmp", exist_ok=True)

    # Re-create after cleanup
    db = SqliteDb(
        db_file=DB_FILE, session_table="team_sessions", approvals_table="approvals"
    )
    deploy_agent = Agent(
        name="Deploy Agent",
        role="Handles deployments to production",
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[deploy_to_production],
    )
    team = Team(
        name="DevOps Team",
        members=[deploy_agent],
        model=OpenAIResponses(id="gpt-5-mini"),
        db=db,
    )

    # Step 1: Run - team will pause
    print("--- Step 1: Running team (expects pause) ---")
    response = team.run("Deploy the payments app version 2.1 to production")
    print(f"Team run status: {response.status}")
    assert response.is_paused, f"Expected paused, got {response.status}"
    print("Team paused as expected.")

    # Step 2: Check approval record
    print("\n--- Step 2: Checking approval record in DB ---")
    approvals_list, total = db.get_approvals(status="pending")
    print(f"Pending approvals: {total}")
    assert total >= 1, f"Expected at least 1 pending approval, got {total}"
    approval_record = approvals_list[0]
    print(f"  Approval ID:  {approval_record['id']}")
    print(f"  Source type:   {approval_record['source_type']}")
    print(f"  Source name:   {approval_record.get('source_name')}")
    print(f"  Context:       {approval_record.get('context')}")

    # Step 3: Confirm and continue
    print("\n--- Step 3: Confirming and continuing ---")
    for req in response.requirements:
        if req.needs_confirmation:
            print(
                f"  Confirming tool: {req.tool_execution.tool_name}({req.tool_execution.tool_args})"
            )
            req.confirm()

    response = team.continue_run(response)
    print(f"Team run status after continue: {response.status}")

    # Step 4: Resolve approval in DB
    print("\n--- Step 4: Resolving approval in DB ---")
    resolved = db.update_approval(
        approval_record["id"],
        expected_status="pending",
        status="approved",
        resolved_by="devops_lead",
        resolved_at=int(time.time()),
    )
    assert resolved is not None, "Approval resolution failed"
    print(f"  Resolved status: {resolved['status']}")
    print(f"  Resolved by:     {resolved['resolved_by']}")

    # Step 5: Verify
    print("\n--- Step 5: Verifying no pending approvals ---")
    count = db.get_pending_approval_count()
    print(f"Remaining pending approvals: {count}")
    assert count == 0

    print("\n--- All checks passed! ---")
    print(f"\nTeam output: {response.content}")
