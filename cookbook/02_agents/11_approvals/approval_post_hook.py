"""
Approval Post Hook
=============================

Demonstrates the post-hook reading the resolved approval record from
run_output.metadata["approval"] after a paused run resumes via DB resolution.

Use case: audit/observability hooks that need to know WHO resolved the
approval and WHEN, not just whether the tool was allowed to run.
"""

import os
import time

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.agent import RunOutput
from agno.tools import tool

DB_FILE = "tmp/approval_post_hook.db"


@approval
@tool(requires_confirmation=True)
def delete_user_data(user_id: str) -> str:
    """Permanently delete all data for a user. This is irreversible.

    Args:
        user_id (str): The user ID whose data should be deleted.
    """
    return f"All data for user {user_id} has been permanently deleted."


def audit_resolved_approval(run_output: RunOutput) -> None:
    """Post-hook: log audit trail using the resolved approval record."""
    if not run_output.metadata:
        return

    approval_record = run_output.metadata.get("approval")
    if approval_record is None:
        return

    print("[audit-hook] tool gated by approval:")
    print(f"  approval_id: {approval_record['id']}")
    print(f"  status:      {approval_record['status']}")
    print(f"  resolved_by: {approval_record.get('resolved_by')}")
    print(f"  resolved_at: {approval_record.get('resolved_at')}")


if __name__ == "__main__":
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
    os.makedirs("tmp", exist_ok=True)

    db = SqliteDb(
        db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
    )
    agent = Agent(
        name="Admin Agent",
        model=OpenAIResponses(id="gpt-5-mini"),
        tools=[delete_user_data],
        post_hooks=[audit_resolved_approval],
        db=db,
    )

    print("--- Step 1: Running agent (expects pause) ---")
    run = agent.run("Delete all data for user U-12345")
    assert run.is_paused, f"Expected paused, got {run.status}"
    print(f"Paused. Run ID: {run.run_id}")

    print("\n--- Step 2: Resolving approval in DB (admin/API path) ---")
    pending, _ = db.get_approvals(run_id=run.run_id, status="pending")
    assert len(pending) == 1
    approval_id = pending[0]["id"]
    resolved = db.update_approval(
        approval_id,
        expected_status="pending",
        status="approved",
        resolved_by="admin@example.com",
        resolved_at=int(time.time()),
    )
    assert resolved is not None
    print(f"  Resolved by: {resolved['resolved_by']}")

    print("\n--- Step 3: Continuing run (post-hook should see resolution) ---")
    run = agent.continue_run(run_id=run.run_id, requirements=run.requirements)
    assert not run.is_paused, "Expected run to complete"

    print("\n--- Step 4: Verifying metadata exposed on RunOutput ---")
    assert run.metadata is not None, "Expected metadata to be populated"
    assert "approval" in run.metadata, "Expected metadata['approval'] to be set"
    assert run.metadata["approval"]["resolved_by"] == "admin@example.com"
    print(f"  metadata['approval'] status: {run.metadata['approval']['status']}")
    print(
        f"  metadata['approval'] resolved_by: {run.metadata['approval']['resolved_by']}"
    )

    print("\n--- All checks passed! ---")
