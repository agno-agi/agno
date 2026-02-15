"""Team HITL Streaming: Rejecting a member agent tool call.

This example demonstrates how the team handles rejection of a tool
call in streaming mode. After rejection, the team continues and the
model responds acknowledging the rejection.

Note: When streaming with member agents, use isinstance() with TeamRunPausedEvent
to distinguish the team's pause from member agent pauses.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.run.team import RunPausedEvent as TeamRunPausedEvent
from agno.team.team import Team
from agno.tools import tool
from agno.utils import pprint

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/team_hitl_stream.db")


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
    db=db,
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="Admin Team",
    members=[admin_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for run_event in team.run("Delete the account for user 'jsmith'", stream=True):
        # Use isinstance to check for team's pause event (not the member agent's)
        if isinstance(run_event, TeamRunPausedEvent):
            print("Team paused - requires confirmation")
            for req in run_event.active_requirements:
                if req.needs_confirmation:
                    print(f"  Tool: {req.tool_execution.tool_name}")
                    print(f"  Args: {req.tool_execution.tool_args}")

                    # Reject the dangerous operation
                    req.reject(note="Account deletion requires manager approval first")

            response = team.continue_run(
                run_id=run_event.run_id,
                session_id=run_event.session_id,
                requirements=run_event.requirements,
                stream=True,
            )
            pprint.pprint_run_response(response)
