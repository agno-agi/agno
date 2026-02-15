"""Team HITL: Rejecting a member agent tool call.

This example demonstrates how the team handles rejection of a tool
call. After rejection, the team continues and the model responds
acknowledging the rejection.
"""

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.team.team import Team
from agno.tools import tool


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def delete_user_account(username: str) -> str:
    """Permanently delete a user account and all associated data.

    Args:
        username (str): Username of the account to delete
    """
    return f"Account {username} has been permanently deleted"


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
admin_agent = Agent(
    name="Admin Agent",
    role="Handles account administration tasks",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[delete_user_account],
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Admin Team",
    members=[admin_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
)

# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    response = team.run("Delete the account for user 'jsmith'")

    if response.is_paused:
        print("Team paused - requires confirmation")
        for req in response.requirements:
            if req.needs_confirmation:
                print(f"  Tool: {req.tool_execution.tool_name}")
                print(f"  Args: {req.tool_execution.tool_args}")

                # Reject the dangerous operation
                req.reject(note="Account deletion requires manager approval first")

        response = team.continue_run(response)
        print(f"Result: {response.content}")
    else:
        print(f"Result: {response.content}")
