"""Audit-only approval: @approval(mode="log") for logging without blocking.

Demonstrates the "log" approval mode. The agent still pauses (via the
underlying HITL flag), but the approval record is marked approval_mode="log"
so the UI can treat it as informational rather than a hard gate.

Run: .venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_log_mode.py
"""

import os
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import approval, tool

DB_FILE = "tmp/approvals_log_mode_test.db"

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.makedirs("tmp", exist_ok=True)


@approval(mode="log")
@tool(requires_confirmation=True)
def send_notification(channel: str, message: str) -> str:
    """Send a notification to a channel.

    Args:
        channel (str): The notification channel.
        message (str): The notification message.
    """
    return f"Notification sent to #{channel}: {message}"


db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[send_notification],
    markdown=True,
    db=db,
)

# Step 1: Run - agent will pause
print("--- Step 1: Running agent (expects pause) ---")
run_response = agent.run(
    "Send a notification to the alerts channel saying 'Server CPU at 95%'"
)
print(f"Run status: {run_response.status}")
assert run_response.is_paused, f"Expected paused, got {run_response.status}"
print("Agent paused as expected.")

# Step 2: Check approval record has mode="log"
print("\n--- Step 2: Checking approval record in DB ---")
approvals, total = db.get_approvals(status="pending")
print(f"Pending approvals: {total}")
assert total >= 1, f"Expected at least 1 pending approval, got {total}"
approval_record = approvals[0]
print(f"  Approval ID:    {approval_record['id']}")
print(f"  Pause type:     {approval_record.get('pause_type')}")
print(f"  Approval mode:  {approval_record.get('approval_mode')}")
assert approval_record.get("approval_mode") == "log", (
    f"Expected approval_mode='log', got '{approval_record.get('approval_mode')}'"
)

# Step 3: Confirm and continue (agent still needs confirmation to proceed)
print("\n--- Step 3: Confirming and continuing ---")
for requirement in run_response.active_requirements:
    if requirement.needs_confirmation:
        print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
        requirement.confirm()

run_response = agent.continue_run(
    run_id=run_response.run_id,
    requirements=run_response.requirements,
)
print(f"Run status after continue: {run_response.status}")
assert not run_response.is_paused, "Expected run to complete"

# Step 4: Resolve approval in DB
print("\n--- Step 4: Resolving approval in DB ---")
resolved = db.update_approval(
    approval_record["id"],
    expected_status="pending",
    status="approved",
    resolved_by="audit_system",
    resolved_at=int(time.time()),
)
assert resolved is not None, "Approval resolution failed"
print(f"  Resolved status: {resolved['status']}")

print("\n--- All checks passed! ---")
print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")
