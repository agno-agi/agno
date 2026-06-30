"""
External Tool Execution (Silent)
================================

Demonstrates external_execution_silent=True with Teams.

When a member's tool has external_execution_silent=True, the Team's
paused content message does NOT show that requirement. This is useful
for frontend tools that execute automatically without user interaction.

Compare output with external_tool_execution.py to see the difference:
- Non-silent: Shows "Team run paused. The following require input: ..."
- Silent: Shows empty content (no verbose message)
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team import Team
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
# Create Members
# ---------------------------------------------------------------------------
ui_agent = Agent(
    name="UIAgent",
    model=OpenAIResponses(id="gpt-5.2"),
    tools=[change_theme, send_notification],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="UITeam",
    model=OpenAIResponses(id="gpt-5.2"),
    members=[ui_agent],
    telemetry=False,
)


# ---------------------------------------------------------------------------
# Demo: Compare silent vs non-silent paused content
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Demo 1: Silent tool only (change_theme)")
    print("=" * 60)

    run_response = team.run("Change the theme to dark mode")

    if run_response.is_paused:
        print(f"Status: paused")
        print(f"Content: '{run_response.content}'")  # Should be empty
        print(f"Active requirements: {len(run_response.active_requirements)}")

        for req in run_response.active_requirements:
            print(f"  - {req.member_agent_name}: {req.tool_execution.tool_name}")
            print(f"    external_execution_silent: {req.external_execution_silent}")

            # Simulate frontend executing the tool
            req.set_external_execution_result("Theme changed to dark")

        run_response = team.continue_run(run_response)

    pprint.pprint_run_response(run_response)

    print("\n" + "=" * 60)
    print("Demo 2: Non-silent tool only (send_notification)")
    print("=" * 60)

    run_response = team.run("Send a notification saying hello")

    if run_response.is_paused:
        print(f"Status: paused")
        print(f"Content: '{run_response.content}'")  # Should show the requirement
        print(f"Active requirements: {len(run_response.active_requirements)}")

        for req in run_response.active_requirements:
            print(f"  - {req.member_agent_name}: {req.tool_execution.tool_name}")
            print(f"    external_execution_silent: {req.external_execution_silent}")

            req.set_external_execution_result("Notification sent")

        run_response = team.continue_run(run_response)

    pprint.pprint_run_response(run_response)
