"""Async approval-backed HITL: @approval + @tool with async agent run.

Same flow as approval_basic.py but uses arun() and acontinue_run().

Run: .venvs/demo/bin/python cookbook/02_agents/human_in_the_loop/approvals/approval_async.py
"""

import asyncio
import json
import os
import time

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.tools import approval, tool

DB_FILE = "tmp/approvals_async_test.db"

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


async def main():
    db = SqliteDb(
        db_file=DB_FILE, session_table="agent_sessions", approvals_table="approvals"
    )
    agent = Agent(
        model=OpenAIChat(id="gpt-4o-mini"),
        tools=[get_top_hackernews_stories],
        markdown=True,
        db=db,
    )

    # Step 1: Async run - agent will pause
    print("--- Step 1: Running agent async (expects pause) ---")
    run_response = await agent.arun("Fetch the top 2 hackernews stories.")
    print(f"Run status: {run_response.status}")
    assert run_response.is_paused, f"Expected paused, got {run_response.status}"
    print("Agent paused as expected.")

    # Step 2: Check approval record in DB
    print("\n--- Step 2: Checking approval record in DB ---")
    approvals, total = db.get_approvals(status="pending")
    print(f"Pending approvals: {total}")
    assert total >= 1, f"Expected at least 1 pending approval, got {total}"
    approval = approvals[0]
    print(f"  Approval ID: {approval['id']}")
    print(f"  Status:      {approval['status']}")

    # Step 3: Confirm and continue async
    print("\n--- Step 3: Confirming and continuing async ---")
    for requirement in run_response.active_requirements:
        if requirement.needs_confirmation:
            print(f"  Confirming tool: {requirement.tool_execution.tool_name}")
            requirement.confirm()

    run_response = await agent.acontinue_run(
        run_id=run_response.run_id,
        requirements=run_response.requirements,
    )
    print(f"Run status after continue: {run_response.status}")
    assert not run_response.is_paused, "Expected run to complete"

    # Step 4: Resolve approval
    print("\n--- Step 4: Resolving approval in DB ---")
    resolved = db.update_approval(
        approval["id"],
        expected_status="pending",
        status="approved",
        resolved_by="async_user",
        resolved_at=int(time.time()),
    )
    assert resolved is not None, "Approval resolution failed"
    print(f"  Resolved status: {resolved['status']}")

    # Step 5: Verify clean state
    print("\n--- Step 5: Verifying no pending approvals ---")
    count = db.get_pending_approval_count()
    print(f"Remaining pending approvals: {count}")
    assert count == 0

    print("\n--- All checks passed! ---")
    print(f"\nAgent output (truncated): {str(run_response.content)[:200]}...")


asyncio.run(main())
