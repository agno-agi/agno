"""
Audit Approval User Input
=============================

Audit approval with user input: @approval(type="audit") + @tool(requires_user_input=True).
"""

import os

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool

DB_FILE = "tmp/approvals_test.db"


@approval(type="audit")
@tool(requires_user_input=True, user_input_fields=["account"])
def transfer_funds(amount: float, account: str) -> str:
    """Transfer funds to an account.

    Args:
        amount (float): The amount to transfer.
        account (str): The destination account (provided by user).

    Returns:
        str: Confirmation of the transfer.
    """
    return f"Transferred ${amount} to {account}"


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[transfer_funds],
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
        tools=[transfer_funds],
        markdown=True,
        db=db,
    )

    # Step 1: Run - agent will pause because the tool requires user input
    print("--- Step 1: Running agent (expects pause) ---")
    run_response = agent.run("Transfer $250 to my savings account.")
    print(f"Run status: {run_response.status}")
    assert run_response.is_paused, f"Expected paused, got {run_response.status}"
    print("Agent paused as expected.")

    # Step 2: Verify no logged approvals exist yet (audit approval creates records AFTER resolution)
    print("\n--- Step 2: Verifying no logged approvals yet ---")
    approvals_list, total = db.get_approvals(approval_type="audit")
    print(f"Logged approvals before resolution: {total}")
    assert total == 0, f"Expected 0 logged approvals before resolution, got {total}"
    print("No logged approvals yet (as expected).")

    # Step 3: Provide user input and continue
    print("\n--- Step 3: Providing user input and continuing ---")
    for requirement in run_response.active_requirements:
        if requirement.needs_user_input:
            print(
                f"  Providing user input for tool: {requirement.tool_execution.tool_name}"
            )
            requirement.provide_user_input({"account": "SAVINGS-9876"})

    run_response = agent.continue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    print(f"Run status after continue: {run_response.status}")
    assert not run_response.is_paused, "Expected run to complete, but it's still paused"

    # Step 4: Verify logged approval record was created after resolution
    print("\n--- Step 4: Verifying logged approval record ---")
    approvals_list, total = db.get_approvals(approval_type="audit")
    print(f"Logged approvals after resolution: {total}")
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
    print("Logged approval record verified.")

    # Step 5: Verify total state
    print("\n--- Step 5: Verifying final state ---")
    pending_count = db.get_pending_approval_count()
    print(f"Pending approvals: {pending_count}")
    assert pending_count == 0, f"Expected 0 pending approvals, got {pending_count}"
    all_approvals, all_total = db.get_approvals(approval_type="audit")
    print(f"Total logged approvals: {all_total}")
    assert all_total == 1, f"Expected 1 logged approval, got {all_total}"

    print("\n--- All checks passed! ---")
    print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")
