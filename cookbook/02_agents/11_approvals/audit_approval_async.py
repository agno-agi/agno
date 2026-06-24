"""
Audit Approval Async
=============================

Async audit approval: @approval(type="audit") + @tool(requires_confirmation=True) with async.
"""

import asyncio
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
        str: Confirmation message.
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
async def main():
    # Clean up from previous runs
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    os.makedirs("tmp", exist_ok=True)

    # Re-create after cleanup
    _db = SqliteDb(
        db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
    )
    _agent = Agent(
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[delete_user_data],
        markdown=True,
        db=_db,
    )

    # Step 1: Async run - agent will pause because the tool requires confirmation
    print("--- Step 1: Running agent async (expects pause) ---")
    run_response = await _agent.arun("Delete all data for user U-99887.")
    print(f"Run status: {run_response.status}")
    assert run_response.is_paused, f"Expected paused, got {run_response.status}"
    print("Agent paused as expected.")

    # Step 2: Verify no approval record yet (logged approvals are created after resolution)
    print("\n--- Step 2: Verifying no approval records yet ---")
    approvals_list, total = _db.get_approvals()
    print(f"Total approvals before resolution: {total}")
    assert total == 0, f"Expected 0 approvals before resolution, got {total}"
    print("No approval records yet (as expected for audit approval).")

    # Step 3: Confirm and continue async
    print("\n--- Step 3: Confirming and continuing async ---")
    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
            requirement.confirm()

    run_response = await _agent.acontinue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    print(f"Run status after continue: {run_response.status}")
    assert not run_response.is_paused, "Expected run to complete, but it's still paused"

    # Step 4: Verify logged approval record was created in DB
    print("\n--- Step 4: Verifying logged approval record in DB ---")
    approvals_list, total = _db.get_approvals(approval_type="audit")
    print(f"Logged approvals: {total}")
    assert total >= 1, f"Expected at least 1 logged approval, got {total}"
    approval_record = approvals_list[0]
    print(f"  Approval ID:    {approval_record['id']}")
    print(f"  Status:         {approval_record['status']}")
    print(f"  Approval type:  {approval_record['approval_type']}")
    assert approval_record["status"] == "approved", (
        f"Expected status 'approved', got {approval_record['status']}"
    )
    assert approval_record["approval_type"] == "audit", (
        f"Expected type 'audit', got {approval_record['approval_type']}"
    )

    print("\n--- All checks passed! ---")
    print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")


if __name__ == "__main__":
    asyncio.run(main())
