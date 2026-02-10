"""Approval with user input: @approval + @tool(requires_user_input=True).

Demonstrates the @approval decorator stacked on a tool that requires
user-provided input. The approval record captures pause_type="user_input"
so the UI knows to render an input form rather than simple approve/reject.

Run: .venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_user_input.py
"""

import os
import time

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import approval, tool

DB_FILE = "tmp/approvals_user_input_test.db"

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
os.makedirs("tmp", exist_ok=True)


@approval
@tool(requires_user_input=True, user_input_fields=["target_env", "rollback_version"])
def deploy_with_params(app_name: str, target_env: str, rollback_version: str) -> str:
    """Deploy an application with user-specified parameters.

    Args:
        app_name (str): Name of the application to deploy.
        target_env (str): Target environment (staging, production).
        rollback_version (str): Version to rollback to if deployment fails.
    """
    return f"Deployed {app_name} to {target_env} (rollback: {rollback_version})"


db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[deploy_with_params],
    markdown=True,
    db=db,
)

# Step 1: Run - agent will pause because the tool requires user input
print("--- Step 1: Running agent (expects pause for user input) ---")
run_response = agent.run("Deploy the payments service")
print(f"Run status: {run_response.status}")
assert run_response.is_paused, f"Expected paused, got {run_response.status}"
print("Agent paused as expected.")

# Step 2: Check that an approval record with pause_type="user_input" was created
print("\n--- Step 2: Checking approval record in DB ---")
approvals, total = db.get_approvals(status="pending")
print(f"Pending approvals: {total}")
assert total >= 1, f"Expected at least 1 pending approval, got {total}"
approval_record = approvals[0]
print(f"  Approval ID:    {approval_record['id']}")
print(f"  Pause type:     {approval_record.get('pause_type')}")
print(f"  Tool name:      {approval_record.get('tool_name')}")
print(f"  Approval mode:  {approval_record.get('approval_mode')}")
assert approval_record.get("pause_type") == "user_input", (
    f"Expected pause_type='user_input', got '{approval_record.get('pause_type')}'"
)

# Step 3: Filter by pause_type
print("\n--- Step 3: Filtering by pause_type ---")
user_input_approvals, ui_total = db.get_approvals(pause_type="user_input")
print(f"User input approvals: {ui_total}")
assert ui_total >= 1

# Step 4: Provide user input and continue
print("\n--- Step 4: Providing user input and continuing ---")
for requirement in run_response.active_requirements:
    if requirement.needs_user_input:
        print(f"  Providing input for: {requirement.tool_execution.tool_name}")
        requirement.provide_user_input(
            {"target_env": "staging", "rollback_version": "1.2.3"}
        )

run_response = agent.continue_run(
    run_id=run_response.run_id,
    requirements=run_response.requirements,
)
print(f"Run status after continue: {run_response.status}")
assert not run_response.is_paused, "Expected run to complete"

# Step 5: Resolve approval in DB
print("\n--- Step 5: Resolving approval in DB ---")
resolved = db.update_approval(
    approval_record["id"],
    expected_status="pending",
    status="approved",
    resolved_by="deployer",
    resolved_at=int(time.time()),
    resolution={
        "action": "approve",
        "values": {"target_env": "staging", "rollback_version": "1.2.3"},
    },
)
assert resolved is not None, "Approval resolution failed"
print(f"  Resolved status: {resolved['status']}")

print("\n--- All checks passed! ---")
print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")
