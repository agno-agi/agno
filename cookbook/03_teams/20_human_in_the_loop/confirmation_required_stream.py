"""Team HITL Streaming: Member agent tool requiring confirmation.

This example demonstrates how a team pauses when a member agent's tool
requires human confirmation in streaming mode. After confirmation the team
resumes with continue_run().

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

# Database is required for continue_run to work - it stores the paused run

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/team_hitl_stream.db")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def deploy_to_production(app_name: str, version: str) -> str:
    """Deploy an application to production.

    Args:
        app_name (str): Name of the application
        version (str): Version to deploy
    """
    return f"Successfully deployed {app_name} v{version} to production"


# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------
deploy_agent = Agent(
    name="Deploy Agent",
    role="Handles deployments to production",
    model=OpenAIResponses(id="gpt-5-mini"),
    tools=[deploy_to_production],
    db=db,
)


# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------
team = Team(
    name="DevOps Team",
    members=[deploy_agent],
    model=OpenAIResponses(id="gpt-5-mini"),
    db=db,
)


# ---------------------------------------------------------------------------
# Run Team
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    for run_event in team.run(
        "Deploy the payments app version 2.1 to production", stream=True
    ):
        # Use isinstance to check for team's pause event (not the member agent's)
        if isinstance(run_event, TeamRunPausedEvent):
            print("Team paused - requires confirmation")
            for req in run_event.active_requirements:
                if req.needs_confirmation:
                    print(f"  Tool: {req.tool_execution.tool_name}")
                    print(f"  Args: {req.tool_execution.tool_args}")
                    req.confirm()

            response = team.continue_run(
                run_id=run_event.run_id,
                session_id=run_event.session_id,
                requirements=run_event.requirements,
                stream=True,
            )
            pprint.pprint_run_response(response)
