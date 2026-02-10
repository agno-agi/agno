"""Approval + user input HITL: @approval + @tool(requires_user_input=True).

This example shows how @approval works with requires_user_input to create
a persistent approval record AND require user input before tool execution.

Run: .venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_user_input.py
"""

import os
import time

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import tool

DB_FILE = "tmp/approvals_test.db"

# Clean up from previous runs
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.makedirs("tmp", exist_ok=True)


@approval
@tool(requires_user_input=True, user_input_fields=["recipient"])
def send_money(amount: float, recipient: str, note: str) -> str:
    """Send money to a recipient.

    Args:
        amount (float): The amount of money to send.
        recipient (str): The recipient to send money to (provided by user).
        note (str): A note to include with the transfer.

    Returns:
        str: Confirmation of the transfer.
    """
    return f"Sent ${amount} to {recipient}: {note}"


db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_money],
    markdown=True,
    db=db,
)

# Step 1: Run - agent will pause because the tool requires approval and user input
print("--- Step 1: Running agent (expects pause) ---")
run_response = agent.run("Send $50 to someone with the note 'lunch money'.")
print(f"Run status: {run_response.status}")
assert run_response.is_paused, f"Expected paused, got {run_response.status}"
print("Agent paused as expected.")

# Step 2: Check that an approval record was created in the DB
print("\n--- Step 2: Checking approval record in DB ---")
approvals, total = db.get_approvals(status="pending", approval_type="required")
print(f"Pending approvals: {total}")
assert total >= 1, f"Expected at least 1 pending approval, got {total}"
approval = approvals[0]
print(f"  Approval ID: {approval['id']}")
print(f"  Run ID:      {approval['run_id']}")
print(f"  Status:      {approval['status']}")
print(f"  Source:      {approval['source_type']}")
print(f"  Context:     {approval.get('context')}")

# Step 3: Provide user input for recipient and confirm
print("\n--- Step 3: Providing user input and confirming ---")
for requirement in run_response.active_requirements:
    if requirement.needs_user_input:
        print(
            f"  Providing user input for tool: {requirement.tool_execution.tool_name}"
        )
        requirement.provide_user_input({"recipient": "Alice"})
    if requirement.needs_confirmation:
        print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
        requirement.confirm()

run_response = agent.continue_run(
    run_id=run_response.run_id,
    requirements=run_response.requirements,
)
print(f"Run status after continue: {run_response.status}")
assert not run_response.is_paused, "Expected run to complete, but it's still paused"

# Step 4: Resolve the approval record in the DB
print("\n--- Step 4: Resolving approval in DB ---")
resolved = db.update_approval(
    approval["id"],
    expected_status="pending",
    status="approved",
    resolved_by="test_user",
    resolved_at=int(time.time()),
)
assert resolved is not None, "Approval resolution failed (possible race condition)"
print(f"  Resolved status: {resolved['status']}")
print(f"  Resolved by:     {resolved['resolved_by']}")

# Step 5: Verify no more pending approvals
print("\n--- Step 5: Verifying no pending approvals ---")
count = db.get_pending_approval_count()
print(f"Remaining pending approvals: {count}")
assert count == 0, f"Expected 0 pending approvals, got {count}"

print("\n--- All checks passed! ---")
print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")
