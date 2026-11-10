"""
Audit Approval Overview
=============================

Overview: @approval vs @approval(type="audit") in the same agent.
"""

import os
import time

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool

DB_FILE = "tmp/approvals_test.db"


@approval
@tool(requires_confirmation=True)
def critical_action(action: str) -> str:
    """Execute a critical action that requires pre-approval.

    Args:
        action (str): The action to execute.

    Returns:
        str: Result of the action.
    """
    return f"Executed critical action: {action}"


@approval(type="audit")
@tool(requires_confirmation=True)
def sensitive_action(action: str) -> str:
    """Execute a sensitive action that is logged after completion.

    Args:
        action (str): The action to execute.

    Returns:
        str: Result of the action.
    """
    return f"Executed sensitive action: {action}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[critical_action, sensitive_action],
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
        tools=[critical_action, sensitive_action],
        markdown=True,
        db=db,
    )

    # Step 1: Run critical action - creates a pending approval record BEFORE execution
    print("--- Step 1: Running critical action (@approval) ---")
    run1 = agent.run("Execute the critical action: deploy to production.")
    print(f"Run status: {run1.status}")
    assert run1.is_paused, f"Expected paused, got {run1.status}"
    print("Agent paused as expected.")

    # Verify required approval record was created in DB (pending, before execution)
    print("\n--- Step 2: Verifying required approval record in DB ---")
    required_approvals, required_total = db.get_approvals(approval_type="required")
    print(f"Required approvals (pending): {required_total}")
    assert required_total >= 1, (
        f"Expected at least 1 required approval, got {required_total}"
    )
    required_approval = required_approvals[0]
    print(f"  Approval ID:    {required_approval['id']}")
    print(f"  Status:         {required_approval['status']}")
    print(f"  Approval type:  {required_approval['approval_type']}")
    assert required_approval["status"] == "pending", (
        f"Expected status 'pending', got {required_approval['status']}"
    )
    assert required_approval["approval_type"] == "required", (
        f"Expected type 'required', got {required_approval['approval_type']}"
    )

    # Confirm and continue the critical action
    print("\n--- Step 3: Confirming and continuing critical action ---")
    for requirement in run1.active_requirements:
        if requirement.needs_confirmation:
            print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
            requirement.confirm()

    run1 = agent.continue_run(
        run_id=run1.run_id,
        requirements=run1.requirements,
    )
    print(f"Run status after continue: {run1.status}")
    assert not run1.is_paused, "Expected run to complete, but it's still paused"

    # Resolve the required approval in DB
    resolved = db.update_approval(
        required_approval["id"],
        expected_status="pending",
        status="approved",
        resolved_by="admin_user",
        resolved_at=int(time.time()),
    )
    assert resolved is not None, "Approval resolution failed"
    print(f"  Resolved required approval: status={resolved['status']}")

    # Step 4: Run sensitive action - creates an audit approval record AFTER execution
    print("\n--- Step 4: Running sensitive action (@approval audit) ---")
    run2 = agent.run("Execute the sensitive action: export user reports.")
    print(f"Run status: {run2.status}")
    assert run2.is_paused, f"Expected paused, got {run2.status}"
    print("Agent paused as expected (confirmation required).")

    # Confirm and continue the sensitive action
    print("\n--- Step 5: Confirming and continuing sensitive action ---")
    for requirement in run2.active_requirements:
        if requirement.needs_confirmation:
            print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
            requirement.confirm()

    run2 = agent.continue_run(
        run_id=run2.run_id,
        requirements=run2.requirements,
    )
    print(f"Run status after continue: {run2.status}")
    assert not run2.is_paused, "Expected run to complete, but it's still paused"

    # Verify logged approval record was created in DB
    print("\n--- Step 6: Verifying logged approval record in DB ---")
    logged_approvals, logged_total = db.get_approvals(approval_type="audit")
    print(f"Logged approvals: {logged_total}")
    assert logged_total >= 1, f"Expected at least 1 logged approval, got {logged_total}"
    logged_approval = logged_approvals[0]
    print(f"  Approval ID:    {logged_approval['id']}")
    print(f"  Status:         {logged_approval['status']}")
    print(f"  Approval type:  {logged_approval['approval_type']}")
    assert logged_approval["status"] == "approved", (
        f"Expected status 'approved', got {logged_approval['status']}"
    )
    assert logged_approval["approval_type"] == "audit", (
        f"Expected type 'audit', got {logged_approval['approval_type']}"
    )

    # Step 7: Query DB filtering by approval_type to show separation
    print("\n--- Step 7: Querying by approval_type to verify separation ---")
    required_list, required_count = db.get_approvals(approval_type="required")
    logged_list, logged_count = db.get_approvals(approval_type="audit")

    print(f"  Required approvals: {required_count}")
    assert required_count == 1, f"Expected 1 required approval, got {required_count}"

    print(f"  Logged approvals:   {logged_count}")
    assert logged_count == 1, f"Expected 1 logged approval, got {logged_count}"

    print(
        f"  Required record: type={required_list[0]['approval_type']}, status={required_list[0]['status']}"
    )
    print(
        f"  Logged record:   type={logged_list[0]['approval_type']}, status={logged_list[0]['status']}"
    )

    print("\n--- All checks passed! ---")
