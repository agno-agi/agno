"""
Audit Approval Confirmation
=============================

Audit approval with confirmation: @approval(type="audit") + @tool(requires_confirmation=True).
Demonstrates both approval and rejection paths.
"""

import os

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool

DB_FILE = "tmp/approvals_test.db"


@approval(type="audit")
@tool(requires_confirmation=True)
def delete_user_data(user_id: str) -> str:
    """Permanently delete all data for a user.

    Args:
        user_id (str): The user ID whose data should be deleted.

    Returns:
        str: Confirmation of the deletion.
    """
    return f"Deleted data for user {user_id}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[delete_user_data],
    markdown=True,
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
        db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
    )
    agent = Agent(
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[delete_user_data],
        markdown=True,
        db=db,
    )

    # ========== Part 1: Approval path ==========

    # Step 1: Run - agent will pause because the tool requires confirmation
    print("--- Step 1: Running agent for approval path (expects pause) ---")
    run_response = agent.run("Delete all data for user U-100.")
    print(f"Run status: {run_response.status}")
    assert run_response.is_paused, f"Expected paused, got {run_response.status}"
    print("Agent paused as expected.")

    # Step 2: Confirm and continue
    print("\n--- Step 2: Confirming and continuing ---")
    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
            requirement.confirm()

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    print(f"Run status after continue: {run_response.status}")
    assert not run_response.is_paused, "Expected run to complete, but it's still paused"

    # Step 3: Verify logged approval record was created
    print("\n--- Step 3: Verifying logged approval record (approved) ---")
    approvals_list, total = db.get_approvals(approval_type="audit")
    print(f"Logged approvals: {total}")
    assert total >= 1, f"Expected at least 1 logged approval, got {total}"
    approval_record = approvals_list[0]
    print(f"  Approval ID: {approval_record['id']}")
    print(f"  Status:      {approval_record['status']}")
    print(f"  Type:        {approval_record['approval_type']}")
    assert approval_record["status"] == "approved", (
        f"Expected 'approved', got {approval_record['status']}"
    )
    assert approval_record["approval_type"] == "audit", (
        f"Expected 'audit', got {approval_record['approval_type']}"
    )
    print("Logged approval record verified (approved).")

    # ========== Part 2: Rejection path ==========

    # Step 4: Run again - agent will pause for a new confirmation
    print("\n--- Step 4: Running agent for rejection path (expects pause) ---")
    run_response = agent.run("Delete all data for user U-200.")
    print(f"Run status: {run_response.status}")
    assert run_response.is_paused, f"Expected paused, got {run_response.status}"
    print("Agent paused as expected.")

    # Step 5: Reject and continue
    print("\n--- Step 5: Rejecting and continuing ---")
    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            print(f"  Rejecting tool: {requirement.tool_execution.tool_name}")
            requirement.reject("Rejected by admin: not authorized")

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    print(f"Run status after continue: {run_response.status}")
    assert not run_response.is_paused, "Expected run to complete, but it's still paused"

    # Step 6: Verify logged approval record for rejection
    print("\n--- Step 6: Verifying logged approval record (rejected) ---")
    approvals_list, total = db.get_approvals(approval_type="audit")
    print(f"Total logged approvals: {total}")
    assert total >= 2, f"Expected at least 2 logged approvals, got {total}"
    # Find the rejected one (most recent)
    rejected = [a for a in approvals_list if a["status"] == "rejected"]
    assert len(rejected) >= 1, (
        f"Expected at least 1 rejected approval, got {len(rejected)}"
    )
    rej = rejected[0]
    print(f"  Approval ID: {rej['id']}")
    print(f"  Status:      {rej['status']}")
    print(f"  Type:        {rej['approval_type']}")
    assert rej["approval_type"] == "audit", (
        f"Expected 'audit', got {rej['approval_type']}"
    )
    print("Logged approval record verified (rejected).")

    # Final check: total logged approvals
    print("\n--- Final: Checking total logged approvals ---")
    all_logged, all_total = db.get_approvals(approval_type="audit")
    print(f"Total logged approvals: {all_total}")
    assert all_total == 2, f"Expected 2 total logged approvals, got {all_total}"

    print("\n--- All checks passed! ---")
