"""
Pre-hooks on continue_run
==========================

Demonstrates that pre-hooks with @hook(run_on_continue=True) run on continue_run,
while regular hooks are skipped (since input was already validated on initial run).

This is the fix for issue #9084.
"""

import json

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.hooks import hook
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.tools import tool

# Track hook executions for demonstration
hook_log = []


# Regular pre-hook - only runs on initial run()
def log_request(run_input, agent):
    """This hook only runs on initial run(), not on continue_run()."""
    hook_log.append(f"[log_request] Initial request: {run_input.input_content[:50]}...")
    print(f"[log_request] Called on initial run for agent: {agent.name}")


# Security hook with @hook(run_on_continue=True) - runs on BOTH run() and continue_run()
@hook(run_on_continue=True)
def security_check(run_input, agent, user_id=None):
    """This hook runs on BOTH run() and continue_run() for security."""
    hook_log.append(f"[security_check] user_id={user_id}")
    print(f"[security_check] Running security check for user: {user_id}")
    # In a real app, you might check permissions, rate limits, etc.


# Audit hook with @hook(run_on_continue=True) - runs on BOTH
@hook(run_on_continue=True)
def audit_log(run_input, agent, session):
    """This hook runs on BOTH run() and continue_run() for audit compliance."""
    hook_log.append(f"[audit_log] session_id={session.session_id}")
    print(f"[audit_log] Logging audit event for session: {session.session_id}")


# Tool that requires confirmation (triggers HITL flow)
@tool(requires_confirmation=True)
def get_top_hackernews_stories(num_stories: int) -> str:
    """Fetch top stories from Hacker News.

    Args:
        num_stories (int): Number of stories to retrieve

    Returns:
        str: JSON string containing story details
    """
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()

    all_stories = []
    for story_id in story_ids[:num_stories]:
        story_response = httpx.get(
            f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
        )
        story = story_response.json()
        if "text" in story:
            story.pop("text", None)
        all_stories.append(story)
    return json.dumps(all_stories)


# Create agent with pre-hooks
agent = Agent(
    id="pre-hooks-demo",
    name="PreHooksDemo",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[get_top_hackernews_stories],
    pre_hooks=[log_request, security_check, audit_log],
    markdown=True,
    db=SqliteDb(session_table="test_session", db_file="tmp/pre_hooks_demo.db"),
)


# Setup AgentOS
agent_os = AgentOS(
    description="Demo: Pre-hooks behavior on continue_run",
    agents=[agent],
)
app = agent_os.get_app()


# Endpoint to check hook execution log
@app.get("/hook-log")
def get_hook_log():
    """Check which hooks have been executed."""
    return {"hook_log": hook_log, "count": len(hook_log)}


@app.post("/hook-log/clear")
def clear_hook_log():
    """Clear the hook log."""
    hook_log.clear()
    return {"status": "cleared"}


if __name__ == "__main__":
    """
    Run the AgentOS and test the HITL flow:

    1. Start the server:
       python agent_pre_hooks_on_continue.py

    2. Make initial request (all 3 hooks run):
       curl -X POST http://localhost:7777/agents/pre-hooks-demo/runs \\
         -F "message=Get 2 top hackernews stories" \\
         -F "stream=false"

       -> Returns paused status with requirement (needs confirmation)
       -> Check http://localhost:7777/hook-log - should show all 3 hooks

    3. Continue the run (only security_check and audit_log run):
       curl -X POST http://localhost:7777/agents/pre-hooks-demo/runs/{run_id}/continue \\
         -F "requirement_id={req_id}" \\
         -F "confirmation=true"

       -> Check http://localhost:7777/hook-log - should show only decorated hooks

    Expected behavior:
    - Initial run: log_request, security_check, audit_log all execute
    - Continue run: ONLY security_check, audit_log execute (they have @hook(run_on_continue=True))
    - log_request is skipped on continue_run (no decorator)
    """
    print("\n" + "=" * 60)
    print("Pre-hooks Demo - Testing @hook(run_on_continue=True)")
    print("=" * 60)
    print("\nHooks configured:")
    print("  - log_request: runs on initial run() ONLY")
    print("  - security_check: runs on BOTH run() and continue_run()")
    print("  - audit_log: runs on BOTH run() and continue_run()")
    print("\nCheck /hook-log endpoint to see which hooks executed")
    print("=" * 60 + "\n")

    agent_os.serve(app="agent_pre_hooks_on_continue:app", port=7777, reload=True)
