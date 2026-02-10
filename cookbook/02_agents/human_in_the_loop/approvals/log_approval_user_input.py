"""Logged approval with user input: @tool(requires_user_input=True, log_approval=True).

This example shows log_approval=True with user input, creating an audit record
after user provides input and the tool executes.

Run: .venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/log_approval_user_input.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool

DB_FILE = "tmp/approvals_test.db"

# Clean up from previous runs
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.makedirs("tmp", exist_ok=True)


@tool(requires_user_input=True, log_approval=True, user_input_fields=["account"])
def transfer_funds(amount: float, account: str) -> str:
    """Transfer funds to an account.

    Args:
        amount (float): The amount to transfer.
        account (str): The destination account (provided by user).

    Returns:
        str: Confirmation of the transfer.
    """
    return f"Transferred ${amount} to {account}"


db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
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

# Step 2: Verify no logged approvals exist yet (log_approval creates records AFTER resolution)
print("\n--- Step 2: Verifying no logged approvals yet ---")
approvals, total = db.get_approvals(approval_type="logged")
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
approvals, total = db.get_approvals(approval_type="logged")
print(f"Logged approvals after resolution: {total}")
assert total >= 1, f"Expected at least 1 logged approval, got {total}"
approval = approvals[0]
print(f"  Approval ID: {approval['id']}")
print(f"  Status:      {approval['status']}")
print(f"  Type:        {approval['approval_type']}")
assert approval["status"] == "approved", (
    f"Expected 'approved', got {approval['status']}"
)
assert approval["approval_type"] == "logged", (
    f"Expected 'logged', got {approval['approval_type']}"
)
print("Logged approval record verified.")

# Step 5: Verify total state
print("\n--- Step 5: Verifying final state ---")
pending_count = db.get_pending_approval_count()
print(f"Pending approvals: {pending_count}")
assert pending_count == 0, f"Expected 0 pending approvals, got {pending_count}"
all_approvals, all_total = db.get_approvals(approval_type="logged")
print(f"Total logged approvals: {all_total}")
assert all_total == 1, f"Expected 1 logged approval, got {all_total}"

print("\n--- All checks passed! ---")
print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")
