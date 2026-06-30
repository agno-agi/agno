"""
External Execution Silent
=========================

Demonstrates external_execution_silent=True with Agents.

When a tool has external_execution_silent=True, the Agent's paused
content message is suppressed. This is useful for frontend tools that
execute automatically without user interaction.

Compare output with approval_external_execution.py to see the difference:
- Non-silent: Shows "I have tools to execute, but it needs external execution."
- Silent: Shows empty content (no verbose message)
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools import tool
from agno.utils import pprint

# ---------------------------------------------------------------------------
# Silent external execution tool - frontend tools that run automatically
# ---------------------------------------------------------------------------


@tool(external_execution=True, external_execution_silent=True)
def change_theme(theme: str) -> str:
    """Change the UI theme. Executed by the frontend automatically."""
    return ""


# ---------------------------------------------------------------------------
# Non-silent external execution tool - requires user action
# ---------------------------------------------------------------------------


@tool(external_execution=True)
def send_notification(message: str) -> str:
    """Send a push notification. Requires user to trigger manually."""
    return ""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/silent_demo.db", session_table="sessions")

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[change_theme, send_notification],
    db=db,
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Demo: Compare silent vs non-silent paused content
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Demo 1: Silent tool only (change_theme)")
    print("=" * 60)

    run_response = agent.run("Change the theme to dark mode")

    if run_response.is_paused:
        print(f"Status: paused")
        print(f"Content: '{run_response.content}'")  # Should be empty
        print(f"Active requirements: {len(run_response.active_requirements)}")

        for req in run_response.active_requirements:
            if req.needs_external_execution:
                print(f"  - {req.tool_execution.tool_name}")
                print(f"    external_execution_silent: {req.external_execution_silent}")
                # Simulate frontend executing the tool
                req.set_external_execution_result("Theme changed to dark")

        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )

    pprint.pprint_run_response(run_response)

    print("\n" + "=" * 60)
    print("Demo 2: Non-silent tool only (send_notification)")
    print("=" * 60)

    run_response = agent.run("Send a notification saying hello")

    if run_response.is_paused:
        print(f"Status: paused")
        print(f"Content: '{run_response.content}'")  # Should show the verbose message
        print(f"Active requirements: {len(run_response.active_requirements)}")

        for req in run_response.active_requirements:
            if req.needs_external_execution:
                print(f"  - {req.tool_execution.tool_name}")
                print(f"    external_execution_silent: {req.external_execution_silent}")
                req.set_external_execution_result("Notification sent")

        run_response = agent.continue_run(
            run_id=run_response.run_id,
            requirements=run_response.requirements,
        )

    pprint.pprint_run_response(run_response)
