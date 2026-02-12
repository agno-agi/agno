"""Approval-backed HITL: @approval + @tool(requires_confirmation=True) with persistent DB record.

This example shows how the @approval decorator builds on requires_confirmation by
writing a persistent approval record to the database when the agent pauses. It:
1. Runs an agent with a tool that requires approval.
2. Verifies the agent pauses and an approval record is created in the DB.
3. Confirms the requirement and continues the run.
4. Verifies the approval record can be resolved in the DB.

Run: .venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_basic.py
"""

import json
import os
import time

import httpx
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
@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories (int): Number of stories to retrieve.

    Returns:
        str: JSON string of story details.
    """
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()
    stories = []
    for story_id in story_ids[:num_stories]:
        story = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        ).json()
        story.pop("text", None)
        stories.append(story)
    return json.dumps(stories)


db = SqliteDb(
    db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
)
agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    tools=[get_top_hackernews_stories],
    markdown=True,
    db=db,
)

# Step 1: Run - agent will pause because the tool requires approval
print("--- Step 1: Running agent (expects pause) ---")
run_response = agent.run("Fetch the top 2 hackernews stories.")
print(f"Run status: {run_response.status}")
assert run_response.is_paused, f"Expected paused, got {run_response.status}"
print("Agent paused as expected.")

# Step 2: Check that an approval record was created in the DB
print("\n--- Step 2: Checking approval record in DB ---")
approvals, total = db.get_approvals(status="pending")
print(f"Pending approvals: {total}")
assert total >= 1, f"Expected at least 1 pending approval, got {total}"
approval = approvals[0]
print(f"  Approval ID: {approval['id']}")
print(f"  Run ID:      {approval['run_id']}")
print(f"  Status:      {approval['status']}")
print(f"  Source:      {approval['source_type']}")
print(f"  Context:     {approval.get('context')}")

# Step 3: Confirm the requirement and continue the run
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
